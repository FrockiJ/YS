#!/usr/bin/env python3
"""Deploy the local YS UAT checkouts to GCP instance-51 through pinned-key SSH."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import posixpath
import re
import shlex
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable

import paramiko


HOST = "34.135.202.252"
PORT = 22
DEFAULT_USER = "domaineadmin"
DEFAULT_KEY = Path.home() / ".ssh" / "ys-instance-51-ed25519"
SECRET_ENV = "DOMAINAI_GCP_SSH_PASSPHRASE"
EXCLUDED_PARTS = {".git", "node_modules", "dist", "runtime", "data", "backups", "tmp", "artifacts", ".pytest_cache", "__pycache__", ".venv"}


def sha256_fingerprint(key: paramiko.PKey) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def connect(args: argparse.Namespace) -> paramiko.Transport:
    passphrase = os.environ.get(SECRET_ENV)
    if not passphrase:
        raise RuntimeError(f"Set ${SECRET_ENV} for this process; do not persist it or write it to a file.")
    if not args.host_key_sha256:
        raise RuntimeError("--host-key-sha256 is required; obtain it independently through the GCP Console before deployment.")
    private_key = paramiko.Ed25519Key.from_private_key_file(str(args.key), password=passphrase)
    transport = paramiko.Transport((args.host, args.port))
    transport.start_client(timeout=20)
    actual = sha256_fingerprint(transport.get_remote_server_key())
    if actual != args.host_key_sha256:
        transport.close()
        raise RuntimeError(f"Remote host key mismatch (received {actual}). Connection aborted.")
    transport.auth_publickey(args.user, private_key)
    if not transport.is_authenticated():
        transport.close()
        raise RuntimeError("SSH public-key authentication was rejected.")
    return transport


def run(transport: paramiko.Transport, command: str, *, check: bool = True) -> tuple[int, str, str]:
    channel = transport.open_session()
    channel.exec_command("bash -lc " + shlex.quote(command))
    stdout = channel.makefile("r", -1).read()
    stderr = channel.makefile_stderr("r", -1).read()
    code = channel.recv_exit_status()
    if check and code:
        raise RuntimeError(f"Remote command failed ({code}): {stderr.strip() or stdout.strip()}")
    return code, stdout, stderr


def sftp_mkdirs(sftp: paramiko.SFTPClient, path: str) -> None:
    current = "/"
    for part in Path(path).parts:
        if part in ("/", ""):
            continue
        current = posixpath.join(current, part)
        try:
            sftp.stat(current)
        except IOError:
            sftp.mkdir(current)


def excluded(relative: Path) -> bool:
    return any(part in EXCLUDED_PARTS or part.startswith(".env") for part in relative.parts)


def create_archive(source: Path, destination: Path) -> None:
    with tarfile.open(destination, "w:gz", dereference=False) as archive:
        for item in source.rglob("*"):
            relative = item.relative_to(source)
            if excluded(relative):
                continue
            archive.add(item, arcname=relative.as_posix(), recursive=False)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def source_env_with_gcp_overrides(source: Path, destination: Path) -> None:
    values: list[str] = []
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        if line.strip().startswith(("YS_VUE_DIR=", "YS_BACKEND_ENV_FILE=", "YS_GCP_")):
            continue
        values.append(line)
    values.extend(
        [
            "",
            "# Added only to the untracked instance-51 environment file.",
            "YS_VUE_DIR=/opt/ys/current-vue",
            "YS_BACKEND_ENV_FILE=/opt/ys/config/instance-51.env",
            "YS_WEB_BIND_ADDRESS=0.0.0.0",
            "YS_WEB_HOST_PORT=80",
            "YS_GCP_DATA_DIR=/srv/ys/gcp/data",
            "YS_GCP_UPLOADS_DIR=/srv/ys/gcp/uploads",
            "YS_GCP_PGDATA_DIR=/srv/ys/gcp/pgdata",
            "YS_GCP_REDISDATA_DIR=/srv/ys/gcp/redisdata",
            "YS_GCP_BACKUPS_DIR=/srv/ys/gcp/backups",
        ]
    )
    destination.write_text("\n".join(values) + "\n", encoding="utf-8")
    os.chmod(destination, 0o600)


def safe_release_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def deploy(args: argparse.Namespace) -> None:
    backend = args.backend.resolve()
    frontend = args.frontend.resolve()
    source_env = args.source_env.resolve()
    dump = args.dump.resolve()
    manifest = args.manifest.resolve()
    for required in (backend / "docker-compose.uat.yml", frontend / "Dockerfile", source_env, dump, manifest):
        if not required.is_file():
            raise RuntimeError(f"Missing required deployment input: {required}")
    try:
        expected_sha256 = json.loads(manifest.read_text(encoding="utf-8-sig"))["dump_sha256"].lower()
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise RuntimeError(f"Invalid database manifest: {manifest}") from error
    actual_sha256 = file_sha256(dump)
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or actual_sha256 != expected_sha256:
        raise RuntimeError("Database dump checksum does not match the source manifest.")

    release_id = args.release_id or safe_release_id()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", release_id):
        raise RuntimeError("Invalid release id.")
    with tempfile.TemporaryDirectory(prefix="ys-instance-51-") as temp_name:
        temp = Path(temp_name)
        backend_archive = temp / "backend.tar.gz"
        frontend_archive = temp / "frontend.tar.gz"
        remote_env = temp / "instance-51.env"
        create_archive(backend, backend_archive)
        create_archive(frontend, frontend_archive)
        source_env_with_gcp_overrides(source_env, remote_env)

        transport = connect(args)
        try:
            sftp = paramiko.SFTPClient.from_transport(transport)
            staging = f"/tmp/ys-gcp/{release_id}"
            run(transport, f"install -d -m 0700 {shlex.quote(staging)}")
            for local, remote_name in ((backend_archive, "backend.tar.gz"), (frontend_archive, "frontend.tar.gz"), (remote_env, "instance-51.env"), (dump, "source.dump"), (manifest, "source.manifest.json")):
                sftp.put(str(local), f"{staging}/{remote_name}")
            sftp.chmod(f"{staging}/instance-51.env", 0o600)
            # Extract the helper before VM preparation; the archive itself is never executed.
            run(transport, f"sudo install -d -m 0755 /tmp/ys-bootstrap-{release_id} && sudo tar -xzf {shlex.quote(staging + '/backend.tar.gz')} -C /tmp/ys-bootstrap-{release_id}")
            data_option = f" --data-device {shlex.quote(args.data_device)}" if args.data_device else ""
            run(transport, f"sudo bash /tmp/ys-bootstrap-{release_id}/scripts/gcp/prepare-vm.sh{data_option}")
            run(
                transport,
                "sudo bash /tmp/ys-bootstrap-{}//scripts/gcp/deploy-release.sh {} {} {}/source.dump {}/source.manifest.json".format(
                    release_id,
                    shlex.quote(release_id),
                    shlex.quote(staging),
                    shlex.quote(staging),
                    shlex.quote(staging),
                ),
            )
            run(transport, f"sudo bash /opt/ys/current-api/scripts/gcp/validate-deploy.sh {shlex.quote(args.base_url)}")
        finally:
            transport.close()
    print(f"Deployment completed: {release_id}")


def probe(args: argparse.Namespace) -> None:
    transport = connect(args)
    try:
        _, stdout, _ = run(
            transport,
            "whoami; hostname; id; sudo -n true && echo SUDO_OK; uname -a; lsblk -f; findmnt -T /srv 2>/dev/null || true; docker --version || true; docker compose version || true",
        )
        print(stdout, end="")
    finally:
        transport.close()


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--host", default=HOST)
    command.add_argument("--port", default=PORT, type=int)
    command.add_argument("--user", default=DEFAULT_USER)
    command.add_argument("--key", default=DEFAULT_KEY, type=Path)
    command.add_argument("--host-key-sha256", required=True)
    subcommands = command.add_subparsers(dest="operation", required=True)
    subcommands.add_parser("probe")
    deploy_parser = subcommands.add_parser("deploy")
    workspace = Path(__file__).resolve().parents[3]
    deploy_parser.add_argument("--backend", default=Path(__file__).resolve().parents[2], type=Path)
    deploy_parser.add_argument("--frontend", default=workspace / "ys-vue-uat", type=Path)
    deploy_parser.add_argument("--source-env", default=workspace / "config" / "uat" / "backend.env", type=Path)
    deploy_parser.add_argument("--dump", required=True, type=Path)
    deploy_parser.add_argument("--manifest", required=True, type=Path)
    deploy_parser.add_argument("--data-device")
    deploy_parser.add_argument("--release-id")
    deploy_parser.add_argument("--base-url", default=f"http://{HOST}")
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        if args.operation == "probe":
            probe(args)
        else:
            deploy(args)
    except (OSError, RuntimeError, paramiko.SSHException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

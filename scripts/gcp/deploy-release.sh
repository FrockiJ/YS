#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo bash deploy-release.sh RELEASE_ID STAGING_DIR [SOURCE_DUMP] [SOURCE_MANIFEST]

STAGING_DIR must contain backend.tar.gz, frontend.tar.gz and instance-51.env.
When SOURCE_DUMP and SOURCE_MANIFEST are supplied, the database is backed up,
restored, and checked before the application containers are started.
EOF
}

[[ $# -ge 2 && $# -le 4 ]] || { usage >&2; exit 2; }
release_id="$1"
staging_dir="$2"
source_dump="${3:-}"
source_manifest="${4:-}"
[[ "$release_id" =~ ^[A-Za-z0-9._-]+$ ]] || { echo 'Unsafe release id.' >&2; exit 2; }
[[ -d "$staging_dir" ]] || { echo "Missing staging directory: $staging_dir" >&2; exit 1; }

release_dir="/opt/ys/releases/${release_id}"
api_dir="${release_dir}/api"
vue_dir="${release_dir}/vue"
env_file="/opt/ys/config/instance-51.env"
project_name="ys-gcp"
backups_dir="/srv/ys/gcp/backups"

[[ ! -e "$release_dir" ]] || { echo "Release already exists: $release_dir" >&2; exit 1; }
install -d -m 0755 "$api_dir" "$vue_dir" /opt/ys/config "$backups_dir"
tar -xzf "${staging_dir}/backend.tar.gz" -C "$api_dir"
tar -xzf "${staging_dir}/frontend.tar.gz" -C "$vue_dir"
install -m 0600 "${staging_dir}/instance-51.env" "$env_file"
ln -sfn "$api_dir" /opt/ys/current-api
ln -sfn "$vue_dir" /opt/ys/current-vue

compose=(docker compose --project-name "$project_name" --env-file "$env_file" -f "$api_dir/docker-compose.uat.yml" -f "$api_dir/docker-compose.gcp.yml")
"${compose[@]}" config -q
"${compose[@]}" up -d postgres redis

for _ in $(seq 1 30); do
  if "${compose[@]}" exec -T postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
"${compose[@]}" exec -T postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

if [[ -n "$source_dump" || -n "$source_manifest" ]]; then
  [[ -n "$source_dump" && -n "$source_manifest" ]] || { echo 'Dump and manifest must be supplied together.' >&2; exit 2; }
  [[ -f "$source_dump" && -f "$source_manifest" ]] || { echo 'Missing source dump or manifest.' >&2; exit 1; }

  existing_tables="$("${compose[@]}" exec -T postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atqc \"SELECT count(*) FROM pg_tables WHERE schemaname = 'public';\"")"
  if [[ "$existing_tables" != 0 ]]; then
    bash "$api_dir/scripts/gcp/backup-db.sh" "${backups_dir}/pre_restore_${release_id}.dump"
  fi

  container_id="$("${compose[@]}" ps -q postgres)"
  docker cp "$source_dump" "${container_id}:/tmp/source.dump"
  "${compose[@]}" exec -T postgres sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges /tmp/source.dump'
  "${compose[@]}" exec -T postgres rm -f /tmp/source.dump
  cp "$source_manifest" "${backups_dir}/source_${release_id}.manifest.json"
  bash "$api_dir/scripts/gcp/verify-db-counts.sh" "${backups_dir}/source_${release_id}.manifest.json"
fi

"${compose[@]}" build api
"${compose[@]}" run --rm --no-deps api python -c '
import os
import subprocess
import urllib.parse

environment = os.environ.copy()
password = urllib.parse.quote(environment["POSTGRES_PASSWORD"], safe="")
environment["ALEMBIC_DATABASE_URL"] = "postgresql+psycopg2://{}:{}@{}:{}/{}".format(
    environment["POSTGRES_USER"],
    password,
    environment["POSTGRES_HOST"],
    environment["POSTGRES_PORT"],
    environment["POSTGRES_DB"],
)
subprocess.run(["alembic", "upgrade", "head"], env=environment, check=True)
'
"${compose[@]}" up -d --build --remove-orphans
rm -rf "$staging_dir"
echo "Release ${release_id} is active."

#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo bash prepare-vm.sh [--data-device /dev/DEVICE]

Installs Docker Engine and prepares the persistent YS directories.  Supplying
--data-device formats an otherwise unused block device as ext4 and mounts it at
/srv/ys.  The command refuses a mounted or formatted device.
EOF
}

data_device=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-device)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      data_device="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo 'Run this script with sudo.' >&2
  exit 1
fi

. /etc/os-release
case "${ID}" in
  ubuntu|debian) ;;
  *) echo "Unsupported OS: ${ID}. Install Docker Engine and rerun." >&2; exit 1 ;;
esac

if [[ -n "$data_device" ]]; then
  [[ -b "$data_device" ]] || { echo "Not a block device: $data_device" >&2; exit 1; }
  if findmnt -rn -S "$data_device" >/dev/null || findmnt -rn -S "${data_device}"* >/dev/null; then
    echo "Refusing to format mounted device: $data_device" >&2
    exit 1
  fi
  if blkid "$data_device" >/dev/null 2>&1; then
    echo "Refusing to format device that already has a filesystem: $data_device" >&2
    exit 1
  fi
  mkfs.ext4 -F "$data_device"
  install -d -m 0755 /srv/ys
  mount "$data_device" /srv/ys
  uuid="$(blkid -s UUID -o value "$data_device")"
  grep -q "UUID=${uuid}" /etc/fstab || echo "UUID=${uuid} /srv/ys ext4 defaults,nofail 0 2" >> /etc/fstab
fi

apt-get update
apt-get install -y ca-certificates curl gnupg jq rsync tar
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
  curl -fsSL https://download.docker.com/linux/${ID}/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi

arch="$(dpkg --print-architecture)"
codename="${VERSION_CODENAME}"
echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${codename} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

install -d -m 0755 /opt/ys/releases /opt/ys/config
install -d -m 0770 /srv/ys/gcp/{pgdata,redisdata,data,uploads,backups}
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]]; then
  usermod -aG docker "$SUDO_USER"
fi

echo 'VM preparation completed.'
echo 'Run a new SSH session before using Docker without sudo.'

#!/usr/bin/env bash
set -euo pipefail

api_dir="${API_DIR:-/opt/ys/current-api}"
env_file="${ENV_FILE:-/opt/ys/config/instance-51.env}"
project_name="${PROJECT_NAME:-ys-gcp}"
backups_dir="${YS_GCP_BACKUPS_DIR:-/srv/ys/gcp/backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="${1:-${backups_dir}/postgres_${timestamp}.dump}"

compose=(docker compose --project-name "$project_name" --env-file "$env_file" -f "$api_dir/docker-compose.uat.yml" -f "$api_dir/docker-compose.gcp.yml")
install -d -m 0770 "$(dirname "$output")"
container_id="$("${compose[@]}" ps -q postgres)"
[[ -n "$container_id" ]] || { echo 'PostgreSQL container is not running.' >&2; exit 1; }

"${compose[@]}" exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges -f /tmp/ys-gcp-backup.dump'
docker cp "${container_id}:/tmp/ys-gcp-backup.dump" "$output"
"${compose[@]}" exec -T postgres rm -f /tmp/ys-gcp-backup.dump
sha256sum "$output" | tee "${output}.sha256"

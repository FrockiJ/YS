#!/usr/bin/env bash
set -euo pipefail

base_url="${1:-http://127.0.0.1}"
api_dir="${API_DIR:-/opt/ys/current-api}"
env_file="${ENV_FILE:-/opt/ys/config/instance-51.env}"
project_name="${PROJECT_NAME:-ys-gcp}"
compose=(docker compose --project-name "$project_name" --env-file "$env_file" -f "$api_dir/docker-compose.uat.yml" -f "$api_dir/docker-compose.gcp.yml")

"${compose[@]}" config -q
"${compose[@]}" ps
for _ in $(seq 1 30); do
  if curl -fsS "${base_url}/api/debug/health" | jq -e '.ok == true' >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS "${base_url}/api/debug/health" | jq -e '.ok == true' >/dev/null
curl -fsSI "${base_url}/" | head -n 1 | grep -Eq ' 200 | 304 '
"${compose[@]}" port web 80 | grep -Eq '(^|:)80$'

for service in api postgres redis extract-worker; do
  container_id="$("${compose[@]}" ps -q "$service")"
  [[ -n "$container_id" ]] || { echo "Expected container is missing: ${service}" >&2; exit 1; }
  if docker inspect -f '{{range $port, $bindings := .NetworkSettings.Ports}}{{if $bindings}}{{range $bindings}}{{printf "%s -> %s:%s\\n" $port .HostIp .HostPort}}{{end}}{{end}}{{end}}' "$container_id" | grep -q .; then
    echo "Unexpected published port for ${service}" >&2
    exit 1
  fi
done

ss -ltnH '( sport = :80 )' | grep -q .
echo 'Deployment health, frontend, and port isolation checks passed.'

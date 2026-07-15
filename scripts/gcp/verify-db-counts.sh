#!/usr/bin/env bash
set -euo pipefail

manifest="${1:?Usage: verify-db-counts.sh /path/to/source-manifest.json}"
api_dir="${API_DIR:-/opt/ys/current-api}"
env_file="${ENV_FILE:-/opt/ys/config/instance-51.env}"
project_name="${PROJECT_NAME:-ys-gcp}"
compose=(docker compose --project-name "$project_name" --env-file "$env_file" -f "$api_dir/docker-compose.uat.yml" -f "$api_dir/docker-compose.gcp.yml")

[[ -f "$manifest" ]] || { echo "Missing manifest: $manifest" >&2; exit 1; }
container_id="$("${compose[@]}" ps -q postgres)"
[[ -n "$container_id" ]] || { echo 'PostgreSQL container is not running.' >&2; exit 1; }

failed=0
while IFS=$'\t' read -r table expected; do
  [[ "$table" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "Unsafe table name in manifest: $table" >&2; exit 1; }
  actual="$("${compose[@]}" exec -T postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atqc 'SELECT count(*) FROM public.${table};'")"
  if [[ "$actual" != "$expected" ]]; then
    echo "Count mismatch for ${table}: expected=${expected}, actual=${actual}" >&2
    failed=1
  else
    echo "Count verified: ${table}=${actual}"
  fi
done < <(jq -r '.table_counts | to_entries[] | select(.value != null) | "\(.key)\t\(.value)"' "$manifest")

[[ $failed -eq 0 ]] || exit 1
"${compose[@]}" exec -T postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atqc \"SELECT extversion FROM pg_extension WHERE extname = 'vector';\"" | grep -q .
echo 'Database counts and pgvector extension verified.'

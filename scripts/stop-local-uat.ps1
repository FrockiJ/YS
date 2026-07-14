[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$env:YS_VUE_DIR = Join-Path $workspaceRoot 'ys-vue-uat'
$env:YS_BACKEND_ENV_FILE = Join-Path $workspaceRoot 'config\uat\backend.env'
docker compose -p ys-uat -f (Join-Path $repoRoot 'docker-compose.uat.yml') down
if ($LASTEXITCODE -ne 0) { throw 'YS UAT failed to stop.' }

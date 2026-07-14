[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$vueDir = Join-Path $workspaceRoot 'ys-vue-uat'
$envFile = Join-Path $workspaceRoot 'config\uat\backend.env'
$composeFile = Join-Path $repoRoot 'docker-compose.uat.yml'

if (-not (Test-Path -LiteralPath $vueDir)) { throw "Missing frontend checkout: $vueDir" }
if (-not (Test-Path -LiteralPath $envFile)) { throw "Missing local environment file: $envFile" }

$existing = docker compose ls --format json | ConvertFrom-Json
if ($existing | Where-Object { $_.Name -eq 'ys-uat' }) {
    throw 'The ys-uat Compose project already exists. Stop it explicitly before starting it again.'
}

$env:YS_VUE_DIR = $vueDir
$env:YS_BACKEND_ENV_FILE = $envFile
docker compose -p ys-uat -f $composeFile up -d --build
if ($LASTEXITCODE -ne 0) { throw 'YS UAT failed to start.' }

$binding = docker compose -p ys-uat -f $composeFile port web 80
if (-not $binding) { throw 'Docker did not allocate a web port.' }
$url = "http://$($binding.Trim())"
Write-Output "YS UAT is running at $url"
Write-Output "Health check: $url/api/debug/health"

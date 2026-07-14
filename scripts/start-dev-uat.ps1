[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path (Split-Path -Parent $projectRoot) 'ys-ai-uat'
$composeFile = Join-Path $backendRoot 'docker-compose.uat.yml'
$envFile = Join-Path (Split-Path -Parent $projectRoot) 'config\uat\backend.env'

if (-not (Test-Path -LiteralPath $composeFile)) {
  throw "YS UAT backend compose file was not found: $composeFile"
}
if (-not (Test-Path -LiteralPath $envFile)) {
  throw "YS UAT local environment file was not found: $envFile"
}

$env:YS_VUE_DIR = $projectRoot
$env:YS_BACKEND_ENV_FILE = $envFile

$webContainer = docker compose -p ys-uat -f $composeFile ps -q web
if (-not $webContainer) {
  throw 'YS UAT is not running. Start F:\Projects\ys\ys-ai-uat\scripts\start-local-uat.ps1 first.'
}

$binding = (docker compose -p ys-uat -f $composeFile port web 80).Trim()
if (-not $binding) {
  throw 'The YS UAT web service has no dynamic loopback binding.'
}

$env:VITE_YS_API_PROXY = "http://$binding"
Write-Host "Vite API proxy: $env:VITE_YS_API_PROXY"
Push-Location $projectRoot
try {
  npm run vite
  exit $LASTEXITCODE
} finally {
  Pop-Location
}

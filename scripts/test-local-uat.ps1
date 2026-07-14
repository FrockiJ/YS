[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$composeFile = Join-Path $repoRoot 'docker-compose.uat.yml'
$env:YS_VUE_DIR = Join-Path $workspaceRoot 'ys-vue-uat'
$env:YS_BACKEND_ENV_FILE = Join-Path $workspaceRoot 'config\uat\backend.env'
$binding = docker compose -p ys-uat -f $composeFile port web 80
if (-not $binding) { throw 'The ys-uat web service is not running.' }
$health = "http://$($binding.Trim())/api/debug/health"
$response = Invoke-RestMethod -Uri $health -TimeoutSec 15
if (-not $response.ok) { throw "Health endpoint returned an unhealthy response: $($response | ConvertTo-Json -Compress)" }
Write-Output "Health check passed: $health"

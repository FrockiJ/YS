[CmdletBinding()]
param(
    [switch]$Public
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$vueDir = Join-Path $workspaceRoot 'ys-vue-uat'
$envFile = Join-Path $workspaceRoot 'config\uat\backend.env'
$composeFile = Join-Path $repoRoot 'docker-compose.uat.yml'
$publicEnvFile = Join-Path $workspaceRoot 'config\uat\public-web.env'

if (-not (Test-Path -LiteralPath $vueDir)) { throw "Missing frontend checkout: $vueDir" }
if (-not (Test-Path -LiteralPath $envFile)) { throw "Missing local environment file: $envFile" }

$existing = docker compose ls --format json | ConvertFrom-Json
if ($existing | Where-Object { $_.Name -eq 'ys-uat' }) {
    throw 'The ys-uat Compose project already exists. Stop it explicitly before starting it again.'
}

$env:YS_VUE_DIR = $vueDir
$env:YS_BACKEND_ENV_FILE = $envFile
Remove-Item Env:YS_UAT_WEB_BIND_ADDRESS -ErrorAction SilentlyContinue
Remove-Item Env:YS_WEB_BIND_ADDRESS -ErrorAction SilentlyContinue
Remove-Item Env:YS_WEB_HOST_PORT -ErrorAction SilentlyContinue

if ($Public) {
    if (-not (Test-Path -LiteralPath $publicEnvFile)) {
        throw "Missing local public UAT configuration: $publicEnvFile"
    }
    $settings = @{}
    Get-Content -LiteralPath $publicEnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $pair = $line.Split('=', 2)
        if ($pair.Count -ne 2) { throw "Invalid public UAT configuration line: $line" }
        $settings[$pair[0].Trim()] = $pair[1].Trim()
    }
    if ($settings['YS_UAT_PUBLIC_ENABLED'] -ne 'true') {
        throw 'Set YS_UAT_PUBLIC_ENABLED=true in public-web.env before starting public UAT.'
    }
    $bindAddress = $settings['YS_UAT_WEB_BIND_ADDRESS']
    $parsedAddress = $null
    if (-not [System.Net.IPAddress]::TryParse($bindAddress, [ref]$parsedAddress) -or $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'YS_UAT_WEB_BIND_ADDRESS must be a local IPv4 address.'
    }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq $bindAddress })) {
        throw "The public bind address is not assigned to this host: $bindAddress"
    }
    $env:YS_UAT_WEB_BIND_ADDRESS = $bindAddress
}

docker compose -p ys-uat -f $composeFile up -d --build
if ($LASTEXITCODE -ne 0) { throw 'YS UAT failed to start.' }

$binding = docker compose -p ys-uat -f $composeFile port web 80
if (-not $binding) { throw 'Docker did not allocate a web port.' }
$url = "http://$($binding.Trim())"
Write-Output "YS UAT is running at $url"
Write-Output "Health check: $url/api/debug/health"
if ($Public) {
    Write-Output 'This temporary HTTP endpoint does not create or modify Windows Firewall rules.'
}

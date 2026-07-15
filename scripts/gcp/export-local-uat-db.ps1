[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$OutputDirectory = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $workspaceRoot 'artifacts\gcp-instance-51' }
$composeFile = Join-Path $repoRoot 'docker-compose.uat.yml'
$env:YS_VUE_DIR = Join-Path $workspaceRoot 'ys-vue-uat'
$env:YS_BACKEND_ENV_FILE = Join-Path $workspaceRoot 'config\uat\backend.env'

if (-not (Test-Path -LiteralPath $env:YS_BACKEND_ENV_FILE)) { throw "Missing UAT env file: $($env:YS_BACKEND_ENV_FILE)" }
if (-not (docker compose -p ys-uat -f $composeFile ps -q postgres)) { throw 'The local ys-uat PostgreSQL container is not running.' }
$settings = @{}
Get-Content -LiteralPath $env:YS_BACKEND_ENV_FILE | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $pair = $line.Split('=', 2)
    if ($pair.Count -eq 2) { $settings[$pair[0].Trim()] = $pair[1] }
}
$postgresUser = $settings['POSTGRES_USER']
$postgresDb = $settings['POSTGRES_DB']
if (-not $postgresUser -or -not $postgresDb) { throw 'POSTGRES_USER and POSTGRES_DB must be set in backend.env.' }

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$dumpPath = Join-Path $OutputDirectory "ys-uat-$timestamp.dump"
$manifestPath = "$dumpPath.manifest.json"
$containerId = (docker compose -p ys-uat -f $composeFile ps -q postgres).Trim()

docker compose -p ys-uat -f $composeFile exec -T postgres pg_dump -U $postgresUser -d $postgresDb -Fc --no-owner --no-privileges -f /tmp/ys-instance-51.dump
if ($LASTEXITCODE -ne 0) { throw 'Local pg_dump failed.' }
docker cp "$containerId`:/tmp/ys-instance-51.dump" $dumpPath
if ($LASTEXITCODE -ne 0) { throw 'Failed to copy the UAT database dump.' }
docker compose -p ys-uat -f $composeFile exec -T postgres rm -f /tmp/ys-instance-51.dump

$counts = [ordered]@{}
foreach ($table in @('users', 'projects', 'conversations', 'messages', 'file_resources', 'documents', 'chunks', 'official_product_profiles')) {
    $exists = ((docker compose -p ys-uat -f $composeFile exec -T postgres psql -U $postgresUser -d $postgresDb -Atqc "SELECT to_regclass('public.$table') IS NOT NULL;") -join '').Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect source table: $table" }
    if ($exists -eq 't') {
        $count = ((docker compose -p ys-uat -f $composeFile exec -T postgres psql -U $postgresUser -d $postgresDb -Atqc "SELECT count(*) FROM public.$table;") -join '').Trim()
        if ($LASTEXITCODE -ne 0) { throw "Unable to count source table: $table" }
        $counts[$table] = [int64]$count
    }
    else {
        $counts[$table] = $null
    }
}

$sha256 = (Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    created_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    source_compose_project = 'ys-uat'
    dump_file = [IO.Path]::GetFileName($dumpPath)
    dump_sha256 = $sha256
    table_counts = $counts
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Set-Content -LiteralPath "$dumpPath.sha256" -Value "$sha256  $([IO.Path]::GetFileName($dumpPath))" -Encoding ascii
Write-Output "Dump: $dumpPath"
Write-Output "Manifest: $manifestPath"

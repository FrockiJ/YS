[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.uat.yml'
$composeText = Get-Content -LiteralPath $composeFile -Raw

if ($composeText -match '(?m)^\s{2}(api|extract-worker|postgres|redis):[\s\S]*?^\s{4}ports:') {
    throw 'Only the web service may publish a host port.'
}
if ($composeText -notmatch '\$\{YS_UAT_WEB_BIND_ADDRESS:-127\.0\.0\.1\}::80') {
    throw 'The web service must use the opt-in dynamic host bind mapping with a loopback default.'
}

$forbiddenPaths = @('F:\\Projects\\py', 'domaineAI', 'domaineVue')
$operationalFiles = @(
    $composeFile,
    (Join-Path $repoRoot '.env.uat.example'),
    (Join-Path $repoRoot 'README.md'),
    (Join-Path $repoRoot 'scripts')
)
foreach ($item in $operationalFiles) {
    $files = if (Test-Path -LiteralPath $item -PathType Container) { Get-ChildItem -LiteralPath $item -File -Recurse } else { @(Get-Item -LiteralPath $item) }
    foreach ($file in $files | Where-Object { $_.Name -ne 'verify-isolation.ps1' }) {
        $text = Get-Content -LiteralPath $file.FullName -Raw
        foreach ($forbidden in $forbiddenPaths) {
            if ($text -match [regex]::Escape($forbidden)) { throw "Forbidden legacy reference '$forbidden' in $($file.FullName)" }
        }
    }
}

Write-Output 'Operational isolation checks passed.'

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$forbiddenPatterns = @('node_modules/**', 'dist/**', '.env*', '.vscode/**')
foreach ($pattern in $forbiddenPatterns) {
  $tracked = git -C $projectRoot ls-files -- $pattern
  if ($tracked) {
    $tracked | Write-Output
    throw "Generated or local-only paths are tracked in the UAT checkout: $pattern"
  }
}

$legacy = rg -n -i 'domaine' $projectRoot -g '!.git/**' -g '!scripts/verify-isolation.ps1'
if ($LASTEXITCODE -eq 0) {
  $legacy | Write-Output
  throw 'Legacy Domaine references remain in the UAT frontend.'
}
if ($LASTEXITCODE -gt 1) { throw 'Isolation scan failed.' }

$assets = rg -n 'wine-0?[12]|wine0?[12]|q-Glass' "$projectRoot\src"
if ($LASTEXITCODE -eq 0) {
  $assets | Write-Output
  throw 'Legacy wine visual references remain in the UAT frontend.'
}
if ($LASTEXITCODE -gt 1) { throw 'Visual asset scan failed.' }

Write-Host 'YS Vue UAT isolation check passed.'

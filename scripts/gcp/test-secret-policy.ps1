[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$docs = @(
    (Join-Path $workspaceRoot 'ins.md'),
    (Join-Path $workspaceRoot 'insGCP.md'),
    (Join-Path $repoRoot '.env.gcp.example')
)

foreach ($document in $docs) {
    if (-not (Test-Path -LiteralPath $document)) { throw "Missing deployment document: $document" }
    $matches = Select-String -LiteralPath $document -Pattern '^\s*DOMAINAI_GCP_SSH_PASSPHRASE\s*=\s*[^#\s].+$' -CaseSensitive:$false
    if ($matches) { throw "Plain SSH passphrase assignment found in $document" }
}

$trackedEnv = git -C $repoRoot ls-files -- '.env.gcp' 'config/gcp/*' 'artifacts/*'
if ($trackedEnv) { throw "Tracked GCP secret or deployment artifact detected: $trackedEnv" }
Write-Output 'GCP deployment documentation contains no plain SSH passphrase or tracked environment artifact.'

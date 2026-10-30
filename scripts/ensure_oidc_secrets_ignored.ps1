$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$gitignore = Join-Path $root ".gitignore"
$entry = ".streamlit/secrets.toml"

if (-not (Test-Path $gitignore)) {
    New-Item -ItemType File -Path $gitignore | Out-Null
}

$existing = Get-Content -Path $gitignore -ErrorAction SilentlyContinue
if ($existing -notcontains $entry) {
    Add-Content -Path $gitignore -Value $entry -Encoding UTF8
    Write-Host "Added $entry to .gitignore"
} else {
    Write-Host "$entry is already ignored"
}

Write-Host "Verify with: git check-ignore -v .streamlit/secrets.toml"

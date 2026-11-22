# Runs the steps of .github/workflows/perception.yml locally (Windows, .venv) and prints CI LOCAL: VERDE / ROSU.
#   powershell -ExecutionPolicy Bypass -File scripts/ci_local.ps1
# Same order and markers as the workflow: ruff -> mypy -> pytest (perception + contract, coverage >= 83).
# The workflow's bash syntax check of scripts/*.sh runs only when bash is on PATH (Git Bash).

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    Write-Error "Missing .venv/Scripts/python.exe. Follow README.md to install the Python environment."
    exit 2
}
$failed = @()

function Invoke-Step([string]$name, [scriptblock]$cmd) {
    Write-Host "== $name" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    try { & $cmd } catch { $global:LASTEXITCODE = 1; Write-Error $_ }
    if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Host "   $name : ROSU (exit $LASTEXITCODE)" -ForegroundColor Red }
    else { Write-Host "   $name : ok" -ForegroundColor Green }
}

$bash = @("$env:ProgramFiles\Git\bin\bash.exe", "${env:ProgramFiles(x86)}\Git\bin\bash.exe") |
    Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1  # Git Bash (System32\bash.exe = WSL)
if ($bash) {
    Invoke-Step "shell syntax" { & $bash -c 'for f in scripts/camera_setup.sh scripts/download_models.sh; do bash -n "$f" || exit 1; done' }
} else { Write-Host "== shell syntax: skipped (Git Bash not found)" -ForegroundColor Yellow }
& $py -c "import pytest_cov" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "pytest-cov missing (the workflow installs it): .venv/Scripts/python.exe -m pip install pytest-cov" -ForegroundColor Red
    Write-Host "CI LOCAL: ROSU (pytest-cov)" -ForegroundColor Red
    exit 1
}
Invoke-Step "ruff" { & $py -m ruff check }
Invoke-Step "mypy" { & $py -m mypy }
Invoke-Step "pytest" {
    & $py -m pytest tests/perception tests/contract -m "not models and not camera" -q `
        --cov=perception --cov-report=term:skip-covered --cov-fail-under=83 -p no:cacheprovider
}

if ($failed.Count -eq 0) { Write-Host "CI LOCAL: VERDE" -ForegroundColor Green; exit 0 }
Write-Host ("CI LOCAL: ROSU (" + ($failed -join ", ") + ")") -ForegroundColor Red
exit 1

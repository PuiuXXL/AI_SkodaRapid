# Runs, locally, the steps of EVERY GitHub workflow that runs on push (.github/workflows/*.yml) and prints
# "CI ALL: VERDE" / "CI ALL: ROSU (...)". The pre-push hook (.githooks/pre-push) calls it and blocks a red push.
#   powershell -ExecutionPolicy Bypass -File scripts/ci_all.ps1            # everything (~4-6 min)
#   powershell -ExecutionPolicy Bypass -File scripts/ci_all.ps1 -Only core,assistant
#   powershell -ExecutionPolicy Bypass -File scripts/ci_all.ps1 -ChangedFile <list>   # only the workflows GitHub
#                                                     would trigger for these paths (the pre-push hook uses this)
# Workflows: perception (scripts/ci_local.ps1), core, assistant, integration, dashboard. perception-models is not
# here: it runs nightly / by hand on GitHub and needs the model downloads.

param([string]$Only = "perception,core,assistant,integration,dashboard", [string]$ChangedFile = "")

$ErrorActionPreference = "Continue"
$run = @($Only -split "[,\s]+" | Where-Object { $_ })  # -File passes "a,b" as one string: split it here
$known = @("perception", "core", "assistant", "integration", "dashboard")
$unknown = $run | Where-Object { $known -notcontains $_ }
if ($unknown) { Write-Host "unknown workflow(s): $($unknown -join ', ') (known: $($known -join ', '))"; exit 2 }

# the "paths:" push filters of .github/workflows/<name>.yml, as path prefixes (keep in sync with the workflows)
$filters = @{
    perception  = @("perception/", "shared/", "core/", "tests/perception/", "tests/contract/", "scripts/", "requirements/p1-", "requirements/p2-core.txt",
                    "pyproject.toml", ".github/workflows/perception.yml")
    core        = @("core/", "shared/", "simulator/", "integrations/", "assistant/", "tests/core/", "tests/simulator/", "tests/contract/",
                    "scripts/fake_perception.py", "scripts/core_command.py", "requirements/p2-core.txt", "pyproject.toml",
                    "requirements/p3-assistant.txt", ".github/workflows/core.yml")
    assistant   = @("assistant/", "shared/", "integrations/", "tests/assistant/", "requirements/p3-assistant.txt",
                    "pyproject.toml", ".github/workflows/assistant.yml")
    integration = @("perception/", "core/", "shared/", "tests/contract/", "tests/integration/", "docs/perception.md",
                    "requirements/p1-perception.txt", "requirements/p2-core.txt", "pyproject.toml",
                    ".github/workflows/integration.yml")
    dashboard   = @("dashboard/", "tests/contract/fixtures/dashboard_", ".github/workflows/dashboard.yml")
}
if ($ChangedFile) {
    $changed = @(Get-Content $ChangedFile | ForEach-Object { $_.Trim() -replace "\\", "/" } | Where-Object { $_ })
    $run = @($known | Where-Object {
        $prefixes = $filters[$_]
        @($changed | Where-Object { $f = $_; @($prefixes | Where-Object { $f.StartsWith($_) }).Count -gt 0 }).Count -gt 0
    })
    Write-Host ("changed files: $($changed.Count); workflows GitHub would run: " + $(if ($run) { $run -join ", " } else { "none" }))
}
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (@($run | Where-Object { $_ -ne "dashboard" }).Count -and -not (Test-Path -LiteralPath $py)) {
    Write-Error "Missing .venv/Scripts/python.exe. Follow README.md to install the Python environment."
    exit 2
}
$failed = @()

function Invoke-Step([string]$name, [scriptblock]$cmd, [bool]$blocking = $true) {
    Write-Host "== $name" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    try { & $cmd } catch { $global:LASTEXITCODE = 1; Write-Error $_ }
    if (-not $blocking -and $LASTEXITCODE -ne 0) {
        Write-Host "   $name : advisory (same as GitHub continue-on-error)" -ForegroundColor Yellow
        return
    }
    if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Host "   $name : ROSU (exit $LASTEXITCODE)" -ForegroundColor Red }
    else { Write-Host "   $name : ok" -ForegroundColor Green }
}

if ($run -contains "perception") {
    Invoke-Step "perception (ci_local.ps1)" { powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ci_local.ps1") }
}
if ($run -contains "core") {
    Invoke-Step "core: runtime imports" { & $py -c "from core.main import create_app; from assistant.tts import speak_message; from assistant.client import AssistantClient" }
    Invoke-Step "core: ruff errors" { & $py -m ruff check core shared integrations simulator tests/core tests/simulator tests/contract --isolated --target-version py311 --select E9,F63,F7,F821 }
    Invoke-Step "core: ruff style" { & $py -m ruff check core shared integrations simulator --isolated --line-length 120 --target-version py311 --select E,F,W,I,UP,B,SIM,RUF } $false
    Invoke-Step "core: pytest" { & $py -m pytest tests/core tests/simulator tests/contract/test_core_reads_p1.py tests/contract/test_dashboard_route.py -q -p no:cacheprovider --cov=core --cov=shared --cov=simulator --cov-report=term:skip-covered --cov-fail-under=93 }
}
if ($run -contains "assistant") {
    Invoke-Step "assistant: ruff errors" { & $py -m ruff check assistant integrations tests/assistant --isolated --target-version py311 --select E9,F63,F7,F821 }
    Invoke-Step "assistant: ruff style" { & $py -m ruff check assistant integrations --isolated --line-length 120 --target-version py311 --select E,F,W,I,UP,B,SIM,RUF } $false
    Invoke-Step "assistant: pytest" { & $py -m pytest tests/assistant -q -p no:cacheprovider --cov=assistant --cov-report=term:skip-covered --cov-fail-under=70 }
}
if ($run -contains "integration") {
    Invoke-Step "integration: contract" { & $py -m pytest tests/contract -q -p no:cacheprovider }
    Invoke-Step "integration: slow" { & $py -m pytest tests/integration -m slow -q -p no:cacheprovider --durations=5 }
}
if ($run -contains "dashboard") {
    Push-Location (Join-Path $root "dashboard")
    if (-not (Test-Path node_modules)) { Invoke-Step "dashboard: npm ci" { npm.cmd ci } }
    Invoke-Step "dashboard: build" { npm.cmd run build }
    Invoke-Step "dashboard: test" { npm.cmd test }
    Pop-Location
}

if ($failed.Count -eq 0) { Write-Host "CI ALL: VERDE" -ForegroundColor Green; exit 0 }
Write-Host ("CI ALL: ROSU (" + ($failed -join ", ") + ")") -ForegroundColor Red
exit 1

# Run benchmarks that work with Azure OpenAI (+ SerpAPI for web search).
# Saves trace logs under log/mcpuniverse/*.log and markdown reports under log/report_*.md
#
# Usage (from repo root):
#   .\scripts\run_azure_benchmarks.ps1
#   .\scripts\run_azure_benchmarks.ps1 -Domains financial_analysis,web_search

param(
    [string]$Domains = "financial_analysis,web_search"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating venv..."
    python -m venv venv
    $VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
}

$VenvPython3 = Join-Path $RepoRoot "venv\Scripts\python3.exe"
if (-not (Test-Path $VenvPython3)) {
    Copy-Item $VenvPython $VenvPython3
}

if (-not (Test-Path (Join-Path $RepoRoot "venv\Lib\site-packages\mcpuniverse"))) {
    Write-Host "Installing mcpuniverse (first run only)..."
    & $VenvPython -m pip install -e . -r requirements.txt -r dev-requirements.txt
}

$env:Path = (Join-Path $RepoRoot "venv\Scripts") + ";" + $env:Path
$env:PYTHONPATH = $RepoRoot

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "log\mcpuniverse") | Out-Null

foreach ($domain in ($Domains -split ",")) {
    $domain = $domain.Trim()
    if (-not $domain) { continue }

    $testFile = Join-Path $RepoRoot "tests\benchmark\mcpuniverse\test_benchmark_$domain.py"
    if (-not (Test-Path $testFile)) {
        Write-Warning "Skipping unknown domain: $domain (no test file)"
        continue
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Running benchmark: $domain" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    & $VenvPython $testFile
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Benchmark failed: $domain (exit $LASTEXITCODE)"
    }
    Write-Host "Completed: $domain" -ForegroundColor Green
}

Write-Host ""
Write-Host "Logs:    log\mcpuniverse\" -ForegroundColor Yellow
Write-Host "Reports: log\report_*.md" -ForegroundColor Yellow

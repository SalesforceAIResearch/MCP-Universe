# Run the financial analysis benchmark on Windows (PowerShell).
# Usage (from repo root):
#   .\scripts\run_financial_analysis.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
$VenvPython3 = Join-Path $RepoRoot "venv\Scripts\python3.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating venv with Anaconda/base python..."
    python -m venv venv
    $VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
}

if (-not (Test-Path (Join-Path $RepoRoot "venv\Lib\site-packages\mcpuniverse"))) {
    Write-Host "Installing mcpuniverse and dependencies (first run only)..."
    & $VenvPython -m pip install -e . -r requirements.txt -r dev-requirements.txt
}

if (-not (Test-Path $VenvPython3)) {
    Copy-Item $VenvPython $VenvPython3
}

$env:Path = (Join-Path $RepoRoot "venv\Scripts") + ";" + $env:Path

Write-Host "Running financial analysis benchmark..."
& $VenvPython tests\benchmark\mcpuniverse\test_benchmark_financial_analysis.py

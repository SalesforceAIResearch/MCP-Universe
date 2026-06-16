param(
    [ValidateSet("quick", "full")]
    [string]$Preset = "quick",
    [switch]$IncludeNotionTasks,
    [string]$Domains = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Ensure-Venv {
    $venvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating venv..."
        python -m venv venv
    }

    $venvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
    $venvPython3 = Join-Path $RepoRoot "venv\Scripts\python3.exe"
    if (-not (Test-Path $venvPython3)) {
        Copy-Item $venvPython $venvPython3
    }

    if (-not (Test-Path (Join-Path $RepoRoot "venv\Lib\site-packages\mcpuniverse"))) {
        Write-Host "Installing dependencies (first run only)..."
        & $venvPython -m pip install -e . -r requirements.txt -r dev-requirements.txt
    }

    return $venvPython
}

function Test-EnvVar([string]$Name) {
    return -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name))
}

function Assert-RequiredEnv {
    param([string[]]$DomainsToRun)

    $missing = New-Object System.Collections.Generic.List[string]

    if (($DomainsToRun -contains "financial_analysis") -or ($DomainsToRun -contains "web_search") -or ($DomainsToRun -contains "3d_design")) {
        if (-not (Test-EnvVar "AZURE_API_KEY")) { $missing.Add("AZURE_API_KEY") }
        if (-not (Test-EnvVar "AZURE_API_BASE")) { $missing.Add("AZURE_API_BASE") }
    }

    if ($DomainsToRun -contains "web_search") {
        if (-not (Test-EnvVar "SERP_API_KEY")) { $missing.Add("SERP_API_KEY") }
    }

    if ($DomainsToRun -contains "3d_design") {
        if (-not (Test-EnvVar "BLENDER_APP_PATH")) { $missing.Add("BLENDER_APP_PATH") }
        if (-not (Test-EnvVar "MCPUniverse_DIR")) { $missing.Add("MCPUniverse_DIR") }
    }

    if ($missing.Count -gt 0) {
        throw "Missing required env vars: $($missing -join ', ')"
    }
}

function Get-Domains {
    if (-not [string]::IsNullOrWhiteSpace($Domains)) {
        return ($Domains -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }

    if ($Preset -eq "quick") {
        # Quick confidence checks with your currently configured stack.
        return @("financial_analysis", "web_search")
    }

    # Full set that matches your configured keys/services.
    return @("financial_analysis", "web_search", "3d_design")
}

$venvPython = Ensure-Venv
$env:Path = (Join-Path $RepoRoot "venv\Scripts") + ";" + $env:Path
$env:PYTHONPATH = $RepoRoot

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "log\mcpuniverse") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "log") | Out-Null

$domainsToRun = Get-Domains
Assert-RequiredEnv -DomainsToRun $domainsToRun

Write-Host ""
Write-Host "Preset: $Preset" -ForegroundColor Cyan
Write-Host "Domains: $($domainsToRun -join ', ')" -ForegroundColor Cyan
Write-Host ""

if ($IncludeNotionTasks) {
    Write-Host "Note: notion tasks are controlled in yaml files." -ForegroundColor Yellow
    Write-Host "      Uncomment them in mcpuniverse\benchmark\configs\mcpuniverse\web_search.yaml" -ForegroundColor Yellow
    Write-Host "      (multi-server_task_google_search_notion_0001..0005)." -ForegroundColor Yellow
    Write-Host ""
}

foreach ($domain in $domainsToRun) {
    $testFile = Join-Path $RepoRoot "tests\benchmark\mcpuniverse\test_benchmark_$domain.py"
    if (-not (Test-Path $testFile)) {
        Write-Warning "Skipping unknown domain: $domain (no test file)"
        continue
    }

    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Running benchmark: $domain" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    & $venvPython $testFile
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark failed: $domain (exit $LASTEXITCODE)"
    }

    Write-Host "Completed: $domain" -ForegroundColor Green
    Write-Host ""
}

Write-Host "Done." -ForegroundColor Green
Write-Host "Runtime logs:      log\mcpuniverse\*.log" -ForegroundColor Yellow
Write-Host "Benchmark reports: log\report_*.md" -ForegroundColor Yellow
Write-Host ""
Write-Host "Tip: use quick preset for iteration:" -ForegroundColor DarkCyan
Write-Host "  .\scripts\run_relevant_benchmarks.ps1 -Preset quick"
Write-Host "Tip: full run with Blender included:" -ForegroundColor DarkCyan
Write-Host "  .\scripts\run_relevant_benchmarks.ps1 -Preset full"

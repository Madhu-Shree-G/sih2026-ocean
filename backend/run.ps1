# OceanView3D backend launcher (Windows PowerShell)
#
#   .\run.ps1            start the API
#   .\run.ps1 setup      create the venv and install dependencies
#   .\run.ps1 data       generate the demo dataset
#   .\run.ps1 test       run the test suite
#   .\run.ps1 smoke      sweep every endpoint

param([string]$Task = "serve")

$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Require-Venv {
    if (-not (Test-Path $Python)) {
        Write-Host "Virtual environment missing. Run: .\run.ps1 setup" -ForegroundColor Yellow
        exit 1
    }
}

switch ($Task.ToLower()) {
    "setup" {
        python -m venv (Join-Path $PSScriptRoot ".venv")
        & $Python -m pip install --upgrade pip
        & $Python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
        & $Python -m pip install cmocean
        Write-Host "`nSetup complete. Next: .\run.ps1 data" -ForegroundColor Green
    }
    "data" {
        Require-Venv
        & $Python (Join-Path $PSScriptRoot "scripts\generate_sample_data.py") @args
    }
    "test" {
        Require-Venv
        & $Python -m pytest (Join-Path $PSScriptRoot "tests")
    }
    "smoke" {
        Require-Venv
        & $Python (Join-Path $PSScriptRoot "scripts\smoke_test.py")
    }
    "serve" {
        Require-Venv
        Write-Host "API   : http://localhost:8000" -ForegroundColor Cyan
        Write-Host "Docs  : http://localhost:8000/docs" -ForegroundColor Cyan
        Write-Host "Health: http://localhost:8000/api/v1/health/ready`n" -ForegroundColor Cyan
        & $Python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
    }
    default {
        Write-Host "Unknown task '$Task'. Use: setup | data | serve | test | smoke"
        exit 1
    }
}

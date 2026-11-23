# U - Secure Daily Expense Tracker | Main Project Launcher
# Compatible with Windows PowerShell 5.1+
$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppUrl = "http://127.0.0.1:8765"
$SonarUrl = "http://localhost:9000"
$ZapReport = Join-Path $ProjectRoot "zap_report.html"

Set-Location -LiteralPath $ProjectRoot

function Get-Python {
    $venvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
    if (Test-Path $venvPython) { return $venvPython }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Start-UApp {
    $python = Get-Python
    if (-not $python) {
        Write-Host "Python not found. Install Python 3.10+ and create the venv first." -ForegroundColor Red
        return
    }
    $quotedRoot = "'" + $ProjectRoot.Replace("'", "''") + "'"
    $quotedPython = "'" + $python.Replace("'", "''") + "'"
    $cmd = "Set-Location -LiteralPath $quotedRoot; & $quotedPython -m flask --app run run --host 127.0.0.1 --port 8765"
    try {
        Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $cmd) | Out-Null
        Start-Sleep -Seconds 2
        Start-Process $AppUrl
        Write-Host "Flask launch requested. A separate PowerShell window should show server output." -ForegroundColor Green
        Write-Host "Application: $AppUrl"
    } catch {
        Write-Host "Could not start Flask: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Run-Tests {
    $python = Get-Python
    if (-not $python) {
        Write-Host "Python not found. Create the venv and install requirements first." -ForegroundColor Red
        return
    }
    Write-Host "`nRunning automated tests..." -ForegroundColor Cyan
    & $python -m pytest -v
    Write-Host "`nPytest exit code: $LASTEXITCODE"
}

function Check-Docker {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "Docker CLI not found." -ForegroundColor Yellow
        return $false
    }
    & docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Docker engine: RUNNING" -ForegroundColor Green
        return $true
    }
    Write-Host "Docker engine: NOT AVAILABLE. Start Docker Desktop and retry." -ForegroundColor Yellow
    return $false
}

function Check-Sonar {
    try {
        $r = Invoke-WebRequest -Uri "$SonarUrl/api/system/status" -UseBasicParsing -TimeoutSec 4
        Write-Host "SonarQube server: REACHABLE ($SonarUrl)" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "SonarQube server: NOT REACHABLE. Start Docker Desktop and the existing SonarQube container if needed." -ForegroundColor Yellow
        return $false
    }
}

function Check-ZapReport {
    if (Test-Path $ZapReport) {
        $f = Get-Item $ZapReport
        Write-Host "ZAP HTML report: FOUND ($($f.Length) bytes)" -ForegroundColor Green
        return $true
    }
    Write-Host "ZAP HTML report: NOT FOUND in project root." -ForegroundColor Yellow
    Write-Host "Copy zap_report.html into: $ProjectRoot"
    return $false
}

function Run-AllChecks {
    Write-Host "`n========== U PROJECT PRE-FLIGHT ==========" -ForegroundColor Cyan
    Run-Tests
    Write-Host "`nChecking Docker..."
    $null = Check-Docker
    Write-Host "`nChecking SonarQube..."
    $null = Check-Sonar
    Write-Host "`nChecking ZAP report..."
    $null = Check-ZapReport
    Write-Host "`nPre-flight complete. Review each result above; this does not run a fresh SonarQube or ZAP scan." -ForegroundColor Cyan
}

function Show-Menu {
    Clear-Host
    Write-Host "==================================================" -ForegroundColor Magenta
    Write-Host "       U - SECURE DAILY EXPENSE TRACKER" -ForegroundColor White
    Write-Host "              MAIN PROJECT LAUNCHER" -ForegroundColor Magenta
    Write-Host "==================================================" -ForegroundColor Magenta
    Write-Host " [1] Start Flask application"
    Write-Host " [2] Run automated tests (pytest)"
    Write-Host " [3] Open application dashboard"
    Write-Host " [4] Open SonarQube dashboard"
    Write-Host " [5] Open OWASP ZAP HTML report"
    Write-Host " [6] Open project folder"
    Write-Host " [7] Run all pre-flight checks"
    Write-Host " [8] Exit"
    Write-Host "--------------------------------------------------"
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Select an option (1-8)"
    switch ($choice) {
        "1" { Start-UApp; Pause }
        "2" { Run-Tests; Pause }
        "3" { Start-Process $AppUrl; Pause }
        "4" { Start-Process $SonarUrl; Pause }
        "5" {
            if (Test-Path $ZapReport) { Start-Process $ZapReport }
            else { Write-Host "zap_report.html was not found in the project root." -ForegroundColor Yellow }
            Pause
        }
        "6" { Start-Process explorer.exe $ProjectRoot; Pause }
        "7" { Run-AllChecks; Pause }
        "8" { return }
        default { Write-Host "Invalid option. Choose 1-8." -ForegroundColor Yellow; Start-Sleep -Seconds 1 }
    }
}

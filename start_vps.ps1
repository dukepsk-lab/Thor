$ErrorActionPreference = "Stop"

Write-Host "========================================="
Write-Host "      THOR VPS STARTUP SCRIPT            "
Write-Host "========================================="

# 1. Build Frontend if missing
$distPath = "web-dashboard\dist"
if (-Not (Test-Path $distPath)) {
    Write-Host "Frontend build not found. Compiling React Dashboard..." -ForegroundColor Yellow
    Push-Location "web-dashboard"
    npm install
    npm run build
    Pop-Location
    Write-Host "Frontend compiled successfully." -ForegroundColor Green
} else {
    Write-Host "Frontend already built." -ForegroundColor Green
}

# 2. Start the API and Dashboard Server in a new window
Write-Host "Starting Dashboard API Server (Port 8000)..." -ForegroundColor Cyan
Start-Process -FilePath "python" -ArgumentList "api.py" -WindowStyle Normal -PassThru

Start-Sleep -Seconds 3
Write-Host "Dashboard available at http://localhost:8000" -ForegroundColor Green

# 3. Start the Master Trading Bot Manager in the current window
Write-Host "Starting Master Trading Engine..." -ForegroundColor Cyan
python manager_bot.py

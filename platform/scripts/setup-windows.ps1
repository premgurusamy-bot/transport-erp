# G ROAD LINES - one-time setup on Windows (PowerShell).  Right-click > Run with PowerShell, or:
#   powershell -ExecutionPolicy Bypass -File platform\scripts\setup-windows.ps1
# Recommended path: Docker Desktop (installs PostgreSQL, API, worker and web in containers).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Write-Host "Docker Desktop is not installed. Install it from https://www.docker.com/products/docker-desktop/ , start it, then run this script again." -ForegroundColor Yellow
  exit 1
}
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  function New-Secret([int]$n) { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count $n | ForEach-Object { [char]$_ }) }
  (Get-Content ".env") `
    -replace "change-me-strong-db-password", (New-Secret 24) `
    -replace "change-me-to-a-long-random-secret-of-at-least-32-chars", (New-Secret 48) `
    -replace "change-me-separate-backup-key", (New-Secret 40) `
    -replace "change-me-tracker-key", (New-Secret 24) | Set-Content ".env"
  Write-Host "Created .env with random secrets. Keep a copy of GRL_BACKUP_KEY somewhere safe (not on this PC only)." -ForegroundColor Green
}
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host "Docker could not build/start the system. Is Docker Desktop running? See docs\DEPLOYMENT.md." -ForegroundColor Red; exit 1 }
Write-Host "Waiting for the system to start (first time can take a few minutes)..."
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
  try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:8080/api/v1/health").StatusCode -eq 200) { $ready = $true; break } } catch { }
  Start-Sleep -Seconds 4
}
if (-not $ready) { Write-Host "The system did not start in time. Run: docker compose logs api   and send the last lines for help." -ForegroundColor Red; exit 1 }
$demo = Read-Host "Load SYNTHETIC demo data for training? (y/N)"
if ($demo -eq "y") { docker compose exec -T api python -m app.seed --demo } else { docker compose exec -T api python -m app.seed }
Write-Host "Write down the Owner password shown above (it is shown only once)." -ForegroundColor Yellow
Write-Host "Open http://localhost:8080 . Install as an app: browser menu > Install G ROAD LINES." -ForegroundColor Green
Start-Process "http://localhost:8080/login"

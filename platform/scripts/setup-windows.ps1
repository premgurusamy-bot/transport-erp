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
Start-Sleep -Seconds 10
$demo = Read-Host "Load SYNTHETIC demo data for training? (y/N)"
if ($demo -eq "y") { docker compose exec api python -m app.seed --demo } else { docker compose exec api python -m app.seed }
Write-Host "Open http://localhost:8080 . Install as an app: browser menu > Install G ROAD LINES." -ForegroundColor Green

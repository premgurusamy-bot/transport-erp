# Encrypted database backup to .\backups (copy this folder to a separate drive/cloud regularly).
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force -Path backups | Out-Null
docker compose exec -T api python scripts/backup.py --out /app/var/backups
docker compose cp api:/app/var/backups/. backups/
Write-Host "Backups in $(Get-Location)\backups" -ForegroundColor Green

# Start G ROAD LINES each day (Docker Desktop must be running).
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose up -d
Start-Process "http://localhost:8080"

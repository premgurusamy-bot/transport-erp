# Developer mode without Docker: needs Python 3.12+, PostgreSQL 16, Node 22.
Set-Location (Split-Path -Parent $PSScriptRoot)
Set-Location backend
if (-not (Test-Path .venv)) { python -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt }
$env:GRL_DATABASE_URL = Read-Host "Database URL (e.g. postgresql+psycopg://postgres:PASSWORD@localhost:5432/groadlines)"
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.seed
Start-Process powershell -ArgumentList "-NoExit", "-Command", ".\.venv\Scripts\uvicorn app.main:app --port 8000"
Set-Location ..\web
if (-not (Test-Path node_modules)) { npm install }
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev"
Start-Process "http://localhost:5173"

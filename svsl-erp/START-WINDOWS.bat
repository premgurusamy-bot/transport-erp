@echo off
REM Local server on a Windows office PC (PostgreSQL + Python 3.12+ + Node 20+ installed). See docs\INSTALL.md
cd /d %~dp0backend
if not exist ..\venv (python -m venv ..\venv)
call ..\venv\Scripts\activate
pip install -r requirements.txt
if not exist ..\frontend\dist (cd ..\frontend && call npm ci && call npm run build && cd ..\backend)
alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8000

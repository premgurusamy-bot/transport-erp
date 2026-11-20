#!/usr/bin/env bash
# Development: API on :8000 (auto-reload) and React on :5173 (proxying /api).
set -e
cd "$(dirname "$0")"
(cd backend && alembic upgrade head && python -m app.seed && uvicorn app.main:app --reload --port 8000) &
(cd frontend && npm run dev) &
wait

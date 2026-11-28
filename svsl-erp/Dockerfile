# Single image: builds the React frontend and serves it from the FastAPI backend.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIST=/app/frontend/dist STORAGE_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd -r -u 1001 svsl && mkdir -p /data && chown svsl /data
USER svsl
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed --create-admin && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]

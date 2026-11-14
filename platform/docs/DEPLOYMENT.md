# Deployment (development, staging, production)

## Environments
| | Development | Staging | Production |
|---|---|---|---|
| `GRL_ENV` | development | staging | production |
| Data | SYNTHETIC demo seed | copy of masters, synthetic transactions | real |
| `GRL_EXPOSE_DEV_OTP` | true | **false** (enforced) | **false** (enforced) |
| `GRL_SECRET_KEY` | any | 32+ random chars (enforced) | 32+ random chars (enforced), from a secret store |
| Integrations | MOCK | provider SANDBOX | LIVE only after verification |

The API refuses to start in staging/production with a weak secret or with development OTP exposure enabled.

## Single server with Docker (office PC or a cloud VM, India region preferred)
```bash
cd platform
cp .env.example .env         # set strong secrets (setup-windows.ps1 does this automatically)
docker compose up -d --build
docker compose exec api python -m app.seed            # roles, chart of accounts, reference data, Owner login
```
Services: `db` (PostgreSQL 16, volume `dbdata`), `redis` (reserved), `api` (FastAPI; runs `alembic upgrade head` on start),
`worker` (scheduled jobs every 5 min), `web` (nginx serving the PWA, proxying `/api`). Port 8080.

For internet exposure put a TLS reverse proxy/load balancer (or the hosting provider's HTTPS) in front of `web`, set
`GRL_CORS_ORIGINS` to the real origin, and point the Android apps at the HTTPS address.

## Upgrades
1. `scripts\backup-windows.ps1` (or `python scripts/backup.py`) – verify the backup file and manifest exist.
2. `git pull` (or copy the new release), `docker compose up -d --build`. Migrations run automatically; they are forward-only Alembic revisions.
3. Check `/api/v1/health`, sign in, open Control Tower.

## Android apps
CI (`.github/workflows/platform.yml`) builds **debug** APKs for both Flutter apps as artifacts. For release: create a signing key
(keep it safe), configure `android/key.properties`, run `flutter build apk --release` (or appbundle). Drivers enter the server address on first launch.

## Windows ERP as an app
Open the ERP address in Edge or Chrome → menu → *Install G ROAD LINES*. It opens in its own window from the Start menu.

## Observability
- Every response has `X-Request-ID`; logs include method, path, status, duration and request id (`docker compose logs -f api`).
- Health: `GET /api/v1/health` (container healthcheck). Worker logs each job's result.
- Integration status: Admin › Integrations. Exceptions and alerts: Control Tower.
- Add central log shipping/metrics (e.g. the hosting provider's logging) when moving to cloud.

## Verified here vs. pending
Verified in the development sandbox: migrations on an empty database, API + web dev servers, all automated tests.
Docker images are built, booted, seeded, signed into and backed up in GitHub Actions on every push (`docker` job); debug APKs are built in the `mobile` job.
Still to do: run the stack on the target Windows PC before the pilot. The API image runs 2 workers (`GRL_API_WORKERS`); with more than one worker the per-process login rate limiter should be replaced by a Redis-backed one.

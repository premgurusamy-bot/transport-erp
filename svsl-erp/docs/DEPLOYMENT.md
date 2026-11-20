# Deployment guide

## Option A – Linux server / cloud VM (recommended)

1. Ubuntu 24.04, 2 vCPU / 4 GB RAM is enough for 24–100 vehicles.
2. Install: `apt install postgresql python3-venv nginx certbot python3-certbot-nginx fonts-dejavu-core`, Node 20+.
3. Copy the project to `/opt/svsl-erp`, create user `svsl`, follow INSTALL.md steps 2–4.
4. `cp deploy/svsl-erp.service /etc/systemd/system/ && systemctl enable --now svsl-erp`
5. `cp deploy/nginx.conf /etc/nginx/sites-enabled/svsl-erp` (change the domain), `certbot --nginx -d erp.yourdomain.in`.
6. In `.env` set `PUBLIC_BASE_URL=https://erp.yourdomain.in`, `CORS_ORIGINS=https://erp.yourdomain.in`, `APP_ENV=production`.
7. HTTPS is required for the driver app's camera and location features on phones.

## Option B – Docker

```bash
cd svsl-erp
cp backend/.env.example .env        # fill SECRET_KEY, DATA_ENCRYPTION_KEY, PUBLIC_BASE_URL; add DB_PASSWORD=...
docker compose up -d --build
docker compose logs app | grep Password     # one-time admin password
```
Data lives in the `db` and `files` volumes. Put nginx (HTTPS) in front for internet access.
*(The Dockerfile has not been built in the development environment – test it once on your server.)*

## Option C – Office PC (Windows)

Run `START-WINDOWS.bat`. Keep the PC on during working hours; use a UPS. For access from outside the office use a VPN
or a cloud deployment rather than opening the port to the internet.

## Workers & scheduler

Run **one** uvicorn worker (the built-in hourly scheduler – alert scan, automatic daily backup, log housekeeping –
runs inside the app process). For more workers, set `RUN_SCHEDULER=false` on all but one, or run a separate
instance with `RUN_SCHEDULER=true`.

## Backups (do not skip)

* Automatic: daily at the hour set in *Settings → Backup* (ZIP with every table + documents, SHA-256 verified; plus a
  `pg_dump` file when `pg_dump` is installed).
* Manual: *Backup → Backup now* before upgrades and month-end closing.
* **Off-site copy**: the backup folder is on the same server. Copy it daily to another disk or cloud storage, e.g.
  `rclone sync /var/backups/svsl-erp remote:svsl-erp-backups` from cron.
* Keep the `DATA_ENCRYPTION_KEY` and `SECRET_KEY` with the backups (separately, securely).
* Restore: *Backup → Restore* (type RESTORE). A safety backup is taken first; users, roles, backup history and the
  audit trail are kept. Command-line alternative: `pg_restore -d svsl_erp --clean <file>.dump`.
* Test a restore on a training database every quarter.

## Upgrades

```bash
cd /opt/svsl-erp && git pull           # or copy the new release
source venv/bin/activate && pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build
systemctl restart svsl-erp             # runs `alembic upgrade head` before starting
```
Take a manual backup first.

## Security checklist

- Strong unique `SECRET_KEY` and `DATA_ENCRYPTION_KEY`; `.env` readable only by the service user.
- HTTPS only; database not exposed to the internet (listen on localhost).
- Enable 2FA for Super Admin, Owner and Accountant users.
- Review *Users → Login history* and *Audit trail* regularly; disable users who leave.
- Set the books lock date (*Settings → Accounts → lock before*) after each month/year closing.

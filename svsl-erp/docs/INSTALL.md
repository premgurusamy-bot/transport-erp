# Installation guide

The ERP runs on one server (office PC, local Linux server or cloud VM). Users open it in a browser on
computers and phones; drivers and customers use the same address.

## 1. Requirements

| Item | Version |
|---|---|
| PostgreSQL | 14 or later (16 recommended) |
| Python | 3.12 or later |
| Node.js | 20 or later (only to build the web app) |
| Disk | 10 GB+ (documents, photos and backups grow over time) |
| Fonts | DejaVu Sans (Linux package `fonts-dejavu-core`) for the ₹ symbol in PDFs; Windows uses `C:\Windows\Fonts` if DejaVu is installed, otherwise PDFs print "Rs." |

## 2. Database

```bash
sudo -u postgres psql
CREATE USER svsl WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE svsl_erp OWNER svsl;
\q
```

## 3. Backend

```bash
cd svsl-erp/backend
python -m venv ../venv && source ../venv/bin/activate      # Windows: ..\venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

| Setting | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://svsl:<password>@localhost:5432/svsl_erp` |
| `SECRET_KEY` | output of `python -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `DATA_ENCRYPTION_KEY` | output of `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` – **keep a copy in a safe place**; Aadhaar and bank numbers cannot be decrypted without it |
| `PUBLIC_BASE_URL` | the address users type, e.g. `https://erp.yourdomain.in` (printed in LR / invoice QR codes) |
| `STORAGE_DIR`, `BACKUP_DIR` | folders for uploaded documents and backups (outside the program folder) |

Create the tables and reference data:

```bash
alembic upgrade head
python -m app.seed          # prints:  Username: admin  Password: Svsl@…   (shown once)
```

## 4. Frontend

```bash
cd ../frontend
npm ci
npm run build               # creates frontend/dist, served by the backend
```

## 5. Start

```bash
cd ../backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<server-ip>:8000`, sign in as **admin** with the printed password and set a new one.

Windows office PC: install PostgreSQL, Python and Node, create the database, fill `backend\.env`, then run
`START-WINDOWS.bat`. Allow port 8000 in Windows Firewall so phones on the office Wi-Fi can connect.

## 6. First-day setup (in the app)

1. **Company** – legal name, GSTIN, PAN, address, state code 33, logo, bank account(s), signatory, LR/invoice terms.
2. **Settings → GST treatments** – review each treatment with your GST practitioner and tick *Verified*. Set the default in *Settings → General → Gst*.
3. **Settings → Numbering** – adjust LR / invoice prefixes before the first document (numbers can only move forward).
4. **Branches**, **Users** (one per person, correct role), **Customers**, **Vehicles** (your 24 vehicles), **Drivers**, **Vendors**, **Routes**.
5. **Rate contracts** per customer (per trip, per number, monthly fixed…).
6. **Compliance → Requirements** – mark what applies; *Generate calendar*.
7. **Settings → Backup** – confirm the daily backup hour; plan an off-site copy (see DEPLOYMENT.md).

## 7. Demo / training database

Create a separate database (e.g. `svsl_training`), point a separate `.env` at it and run
`python -m app.seed --demo`. Demo records are named *DEMO …* and vehicle numbers use the non-existent
state code `00`.

## 8. Running the tests

```bash
createdb svsl_erp_test
cd backend
TEST_DATABASE_URL=postgresql+psycopg://svsl:<pw>@localhost:5432/svsl_erp_test python -m pytest -q
```
The test database is wiped on every run – never point it at real data.

"""Issue an A Prime Transport ERP licence key (for the software provider only).

    python scripts/issue_licence.py --key-file aprime-licence-signing-key.pk8.b64 \
        --to "Customer Transports Pvt Ltd" --iid 1A2B-3C4D-5E6F-7A8B --plan yearly --users 10

The signing key file is the provider's secret. Never put it in this repository, e-mail it or give it to a customer:
anyone holding it can make licence keys. Plans: trial (extension), monthly, quarterly, half_yearly, yearly, perpetual.
--iid "*" makes a key that works on any installation (use only for cloud servers you run yourself).
"""
from __future__ import annotations

import argparse
import base64
import json
import secrets
from datetime import date, timedelta

from cryptography.hazmat.primitives.serialization import load_der_private_key

MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def until_for(plan: str, start: date, days: int | None) -> date | None:
    if plan == "perpetual":
        return None
    if plan == "trial":
        return start + timedelta(days=(days or 15) - 1)
    return add_months(start, MONTHS[plan]) - timedelta(days=1)


def sign(private_der: bytes, payload: dict) -> str:
    key = load_der_private_key(private_der, password=None)
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = key.sign(f"APRIME1.{body}".encode())
    return f"APRIME1.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--to", required=True, help="customer's company name")
    ap.add_argument("--iid", required=True, help="installation ID from the customer's Admin → Licence screen, or *")
    ap.add_argument("--plan", required=True, choices=["trial", "monthly", "quarterly", "half_yearly", "yearly", "perpetual"])
    ap.add_argument("--from", dest="start", default=date.today().isoformat())
    ap.add_argument("--until", help="override the end date (YYYY-MM-DD)")
    ap.add_argument("--days", type=int, help="length of a trial extension in days (default 15)")
    ap.add_argument("--users", type=int, default=0, help="maximum staff users (0 = unlimited)")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    start = date.fromisoformat(a.start)
    until = date.fromisoformat(a.until) if a.until else until_for(a.plan, start, a.days)
    iid = a.iid.strip().upper()
    payload = {"v": 1, "k": "k1", "id": f"AP-{date.today():%Y%m%d}-{secrets.token_hex(2).upper()}", "to": a.to.strip(), "iid": iid, "plan": a.plan,
               "from": start.isoformat(), "until": until.isoformat() if until else None, "users": a.users, "issued": date.today().isoformat(), "note": a.note}
    der = base64.b64decode(open(a.key_file, encoding="ascii").read().strip())
    print(f"Licence {payload['id']} for {payload['to']} ({a.plan}, {payload['from']} – {payload['until'] or 'lifetime'}, users: {a.users or 'unlimited'})\n")
    print(sign(der, payload))


if __name__ == "__main__":
    main()

import os
import shutil
import tempfile
from datetime import date

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/svsl_erp_test")
os.environ["DATABASE_URL"] = TEST_DB
os.environ["RUN_SCHEDULER"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-" + "x" * 40
_storage = tempfile.mkdtemp(prefix="svsl-test-")
os.environ["STORAGE_DIR"] = _storage
os.environ["FRONTEND_DIST"] = os.path.join(_storage, "no-dist")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import SessionLocal, reset_engine  # noqa: E402
from app.models import Base  # noqa: E402

ADMIN_PW = "Admin@12345"


@pytest.fixture(scope="session", autouse=True)
def database():
    eng = create_engine(TEST_DB)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    Base.metadata.create_all(eng)
    eng.dispose()
    reset_engine(TEST_DB)
    from app.seed import bootstrap

    db = SessionLocal()
    bootstrap(db, ADMIN_PW)
    from app.models import User

    db.query(User).filter_by(username="admin").update({"must_change_password": False})
    db.commit()
    db.close()
    yield
    shutil.rmtree(_storage, ignore_errors=True)


@pytest.fixture(scope="session")
def client(database):
    from app.main import app

    with TestClient(app) as c:
        yield c


def login(client, username, password, otp=None):
    r = client.post("/api/auth/login", json={"username": username, "password": password, **({"otp": otp} if otp else {})})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, "admin", ADMIN_PW)


class Api:
    def __init__(self, client, headers):
        self.c, self.h = client, headers

    def get(self, url, **kw):
        r = self.c.get(url, headers=self.h, **kw)
        assert r.status_code < 300, f"GET {url}: {r.status_code} {r.text}"
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r

    def post(self, url, json=None, expect=None, **kw):
        r = self.c.post(url, headers=self.h, json=json, **kw)
        if expect:
            assert r.status_code == expect, f"POST {url}: expected {expect}, got {r.status_code} {r.text}"
            return r
        assert r.status_code < 300, f"POST {url}: {r.status_code} {r.text}"
        return r.json()

    def put(self, url, json=None, expect=None):
        r = self.c.put(url, headers=self.h, json=json)
        if expect:
            assert r.status_code == expect, r.text
            return r
        assert r.status_code < 300, f"PUT {url}: {r.status_code} {r.text}"
        return r.json()


@pytest.fixture(scope="session")
def api(client, admin):
    return Api(client, admin)


_counter = {"n": 0}


def uniq(prefix="X"):
    _counter["n"] += 1
    return f"{prefix}{_counter['n']:03d}"


@pytest.fixture(scope="session")
def company(api):
    return api.put("/api/company", {"legal_name": "Sree Venkateswara Logistics", "trade_name": "Sree Venkateswara Logistics", "state": "Tamil Nadu", "state_code": "33", "city": "Coimbatore"})


@pytest.fixture(scope="session")
def bank(api, company):
    return api.post("/api/r/bank_accounts", {"bank_name": "TEST BANK", "account_no": "000011112222", "ifsc": "SBIN0001234"})


def make_customer(api, state="33", **kw):
    return api.post("/api/r/customers", {"code": uniq("C"), "name": f"Test Customer {uniq()}", "billing_state_code": state, "credit_limit": kw.pop("credit_limit", 1000000), "credit_days": 30, **kw})


def make_vehicle(api, **kw):
    n = uniq()
    return api.post("/api/r/vehicles", {"registration_no": f"TN00TS{n[1:]:0>4}", "vehicle_type": "Closed Body Truck", "ownership": "Owned", "gvw_kg": 25000, "tare_kg": 9000, "expected_kmpl": 4, "current_odometer": 1000, **kw})


def make_driver(api, **kw):
    return api.post("/api/r/drivers", {"code": uniq("D"), "name": f"Driver {uniq()}", "mobile": "9876543210", "licence_no": uniq("DL"), "licence_expiry": str(date(date.today().year + 3, 1, 1)), "daily_bata": 400, "food_allowance_per_day": 100, "trip_allowance": 200, **kw})


def make_contract(api, customer_id, basis="per_trip", rate=12000, **kw):
    return api.post("/api/r/rate_contracts", {"name": f"Contract {uniq()}", "customer_id": customer_id, "basis": basis, "rate": rate, "effective_from": "2020-04-01", "status": "Active", **kw})


def lr_payload(customer_id, **kw):
    return {"customer_id": customer_id, "consignor_name": "Consignor Ltd", "consignee_name": "Consignee Ltd", "from_place": "Coimbatore", "to_place": "Chennai",
            "items": [{"description": "Auto parts", "packages": 10, "quantity": 100, "weight_kg": 5000, "hsn": "8708"}], **kw}

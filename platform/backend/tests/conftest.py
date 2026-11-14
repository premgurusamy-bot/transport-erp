"""Test setup: a dedicated PostgreSQL test database, rebuilt from the migrations' metadata, seeded with roles,
reference data and SYNTHETIC demo users. Tests talk to the API exactly like the apps do."""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("GRL_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/groadlines_test")
os.environ["GRL_ENV"] = "test"
os.environ["GRL_EXPOSE_DEV_OTP"] = "true"
os.environ.setdefault("GRL_STORAGE_DIR", "/tmp/grl-test-storage")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import get_engine  # noqa: E402
from app.models import Base  # noqa: E402

PASSWORD = "Demo@12345"


@pytest.fixture(scope="session")
def client():
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    Base.metadata.create_all(eng)
    os.environ["GRL_ADMIN_PASSWORD"] = "Owner@12345"
    from app.seed import run
    run(demo=True)
    from app.main import app
    with TestClient(app) as c:
        yield c


class Api:
    def __init__(self, client: TestClient, token: str, app: str = "web"):
        self.c, self.h = client, {"Authorization": f"Bearer {token}", "X-GRL-App": app}

    def _do(self, method, url, expect, **kw):
        r = self.c.request(method, url, headers=self.h, **kw)
        if expect is not None:
            assert r.status_code == expect, f"{method} {url} -> {r.status_code}: {r.text[:1500]}"
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r

    def get(self, url, expect=200, **kw):
        return self._do("GET", url, expect, **kw)

    def post(self, url, json=None, expect=200, **kw):
        return self._do("POST", url, expect, json=json, **kw)

    def patch(self, url, json=None, expect=200):
        return self._do("PATCH", url, expect, json=json)

    def put(self, url, json=None, expect=200):
        return self._do("PUT", url, expect, json=json)


def login(client, ident, password=PASSWORD, app="web") -> Api:
    r = client.post("/api/v1/auth/login", json={"identifier": ident, "password": password})
    assert r.status_code == 200, r.text
    return Api(client, r.json()["token"], app)


def otp_login(client, phone, app="driver") -> Api:
    r = client.post("/api/v1/auth/otp/request", json={"phone": phone})
    otp = r.json()["dev_otp"]
    r = client.post("/api/v1/auth/otp/verify", json={"phone": phone, "otp": otp})
    assert r.status_code == 200, r.text
    return Api(client, r.json()["token"], app)


@pytest.fixture(scope="session")
def owner(client):
    return login(client, "owner@groadlines.local", "Owner@12345")


@pytest.fixture(scope="session")
def ops(client):
    return login(client, "operations.manager@demo.local")


@pytest.fixture(scope="session")
def dispatcher(client):
    return login(client, "dispatcher@demo.local")


@pytest.fixture(scope="session")
def accounts(client):
    return login(client, "accounts@demo.local")


@pytest.fixture(scope="session")
def lookup(owner):
    return owner.get("/api/v1/masters/lookup")


def loc(lookup, city):
    return next(x["id"] for x in lookup["locations"] if x["label"].startswith(city + ","))


def uniq(prefix="X"):
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"

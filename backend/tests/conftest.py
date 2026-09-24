"""Test fixtures: isolated database (never the dev/live database)."""
from __future__ import annotations

import os
import sys
import tempfile

# Must be set before any app import so the engine binds to the test database.
_TEST_DB = os.path.join(tempfile.gettempdir(), f"niecp-test-{os.getpid()}.db")
os.environ["NIECP_DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("NIECP_ENV_FILE", "/dev/null")  # don't pick up a dev .env
os.environ.setdefault("NIECP_RATE_LIMIT_PER_MINUTE", "1000000")  # tests make many API calls — never throttle the suite

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.services.seed import run_seed


@pytest.fixture(scope="session", autouse=True)
def _db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    run_seed(db)
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def user_token(client):
    import random

    email = f"test{random.randint(100000, 999999)}@niecp.test"
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Test!Str0ng#9", "full_name": "Test User", "organization_name": "Test Org"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_token(client):
    r = client.post("/api/v1/auth/login", json={"email": "admin@niecp.local", "password": "NIECP-Admin!2026"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def demo_token(client):
    r = client.post("/api/v1/auth/login", json={"email": "demo@niecp.local", "password": "Demo!Demo!123"})
    assert r.status_code == 200
    return r.json()["access_token"]

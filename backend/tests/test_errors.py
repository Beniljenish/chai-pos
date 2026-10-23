"""The app's own error log (README, "9.28")."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.time import utcnow
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import AppError
from app.services import errors
from tests.conftest import platform_headers

API = "/api/v1"


def test_an_app_error_is_logged_scrubbed_and_only_the_platform_admin_reads_it(client, shop_a):
    r = client.post(
        f"{API}/public/app-errors",
        json={
            "message": "TypeError: x is undefined for 9840012345 password=hunter2",
            "place": "/order/court",
            "detail": "at Cart (CustomerApp.tsx:12)",
        },
    )
    assert r.status_code == 204
    assert client.get(f"{API}/platform/errors").status_code == 401
    assert client.get(f"{API}/platform/errors", headers=shop_a.owner_h).status_code == 401
    rows = client.get(f"{API}/platform/errors", headers=platform_headers(client)).json()["errors"]
    mine = next(e for e in rows if e["place"] == "/order/court")
    assert mine["source"] == "app"
    assert "9840012345" not in mine["message"] and "[number]" in mine["message"]
    assert "hunter2" not in mine["message"]


def test_a_server_crash_is_logged_and_answered_with_a_plain_500(client):
    app = client.app

    def boom():
        raise RuntimeError("kaboom")

    app.add_api_route(f"{API}/test-boom", boom)
    quiet = TestClient(app, raise_server_exceptions=False)
    r = quiet.get(f"{API}/test-boom")
    assert r.status_code == 500 and "kaboom" not in r.text
    with mark_system(SessionLocal()) as db:
        row = db.scalar(select(AppError).where(AppError.place == f"GET {API}/test-boom"))
    assert row is not None and row.source == "server" and "kaboom" in row.message
    assert "RuntimeError" in row.detail


def test_reports_from_one_address_are_capped(client):
    for _ in range(35):
        assert client.post(f"{API}/public/app-errors", json={"message": "spam"}).status_code == 204
    with mark_system(SessionLocal()) as db:
        n = len(db.scalars(select(AppError).where(AppError.message == "spam")).all())
    assert n == 30


def test_the_daily_sweep_drops_errors_older_than_30_days():
    errors.record("app", "old one", place="sweep-test")
    with mark_system(SessionLocal()) as db:
        row = db.scalar(select(AppError).where(AppError.place == "sweep-test"))
        row.at = utcnow() - timedelta(days=31)
        db.commit()
        assert errors.sweep(db) >= 1
        db.commit()
        assert db.scalar(select(AppError).where(AppError.place == "sweep-test")) is None

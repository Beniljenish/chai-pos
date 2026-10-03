"""Emails to the owner: right content, right moment, never twice, never across
shops, and a failing email provider never breaks billing."""

import base64
import csv
import io
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.time import business_date, utcnow
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import EmailOutbox, EmailStatus
from app.services import email
from app.services.reports import rupees, week_before
from tests.conftest import FakeDevice, build_catalogue

OWNER_EMAIL = "owner@example.com"


class Recorder:
    def __init__(self, fail: Exception | None = None):
        self.calls: list[tuple[list[email.Message], str]] = []
        self.fail = fail

    def __call__(self, messages, key):
        self.calls.append((messages, key))
        if self.fail:
            raise self.fail
        return [f"id-{len(self.calls)}-{i}" for i in range(len(messages))]

    @property
    def messages(self):
        return [m for batch, _ in self.calls for m in batch]


@pytest.fixture
def sent():
    rec = Recorder()
    email.set_transport(rec)
    yield rec
    email.set_transport(None)


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


def _settings(client, shop, **kw):
    r = client.patch("/api/v1/shop", json=kw, headers=shop.owner_h)
    assert r.status_code == 200, r.text
    return r.json()


def _rows(**where):
    with SessionLocal() as s:
        mark_system(s)
        q = select(EmailOutbox)
        for k, v in where.items():
            q = q.where(getattr(EmailOutbox, k) == v)
        return s.scalars(q).all()


# ---------------------------------------------------------------- formatting
@pytest.mark.parametrize(
    ("paise", "text"),
    [(2000, "₹20"), (1234567, "₹12,345.67"), (10_000_000, "₹1,00,000"), (-338, "-₹3.38")],
)
def test_rupees_use_indian_grouping(paise, text):
    assert rupees(paise) == text


def test_weekly_export_goes_out_on_mondays_for_the_week_just_ended():
    assert week_before(date(2026, 10, 5)) == (date(2026, 9, 28), date(2026, 10, 4))  # Monday
    assert week_before(date(2026, 10, 6)) is None


# ---------------------------------------------------------------- settings
def test_report_settings_and_address_validation(client, shop_a):
    out = _settings(client, shop_a, report_email=" Owner@Example.com ", email_each_bill=True)
    assert out["report_email"] == "owner@example.com" and out["email_each_bill"] is True
    assert (out["email_day_end"], out["email_daily"], out["email_weekly"]) == (True, True, True)
    bad = client.patch(
        "/api/v1/shop", json={"report_email": "not-an-email"}, headers=shop_a.owner_h
    )
    assert bad.status_code == 422
    assert _settings(client, shop_a, report_email="")["report_email"] is None  # cleared


# ---------------------------------------------------------------- every bill
def test_no_address_means_no_email(client, shop_a, cat, sent):
    _settings(client, shop_a, email_each_bill=True)
    d = FakeDevice(client, shop_a)
    d.sync([d.bill([("Masala tea", 1, [])])])
    assert _rows() == [] and sent.calls == []


def test_each_bill_is_emailed_once_in_one_batch(client, shop_a, cat, sent):
    _settings(client, shop_a, report_email=OWNER_EMAIL, email_each_bill=True)
    d = FakeDevice(client, shop_a)
    bills = [d.bill([("Masala tea", 2, [])]), d.bill([("Orange juice", 1, [])])]
    d.sync(bills)
    assert len(sent.calls) == 1  # one provider call for the whole sync
    assert sorted(m.subject for m in sent.messages) == sorted(
        [f"₹40 · {bills[0]['invoice_no']} · Cash", f"₹60 · {bills[1]['invoice_no']} · Cash"]
    )
    assert sent.calls[0][1].startswith("batch:")
    # The tablet resends the same bills (lost reply): no new email.
    d.sync(bills)
    assert len(sent.calls) == 1 and len(_rows(kind="bill")) == 2


def test_each_bill_is_off_by_default(client, shop_a, cat, sent):
    _settings(client, shop_a, report_email=OWNER_EMAIL)
    d = FakeDevice(client, shop_a)
    d.sync([d.bill([("Masala tea", 1, [])])])
    assert _rows(kind="bill") == []


def test_item_names_are_escaped(client, shop_a, sent):
    h = shop_a.owner_h
    client.post("/api/v1/menu-items", json={"name": "<b>Chai</b>", "price_paise": 1500}, headers=h)
    _settings(client, shop_a, report_email=OWNER_EMAIL, email_each_bill=True)
    d = FakeDevice(client, shop_a)
    d.sync([d.bill([("<b>Chai</b>", 1, [])])])
    html = sent.messages[0].html
    assert "&lt;b&gt;Chai&lt;/b&gt;" in html and "<b>Chai</b>" not in html


# ---------------------------------------------------------------- provider failures
def test_a_failing_provider_never_breaks_billing_and_is_retried(client, shop_a, cat):
    rec = Recorder(fail=RuntimeError("provider down"))
    email.set_transport(rec)
    try:
        _settings(client, shop_a, report_email=OWNER_EMAIL, email_each_bill=True)
        d = FakeDevice(client, shop_a)
        r = d.sync([d.bill([("Masala tea", 1, [])])])
        assert r.status_code == 200 and r.json()["results"][0]["status"] == "accepted"
        (row,) = _rows(kind="bill")
        assert row.status == EmailStatus.pending and row.attempts == 1
        assert "provider down" in row.last_error
        for _ in range(email.MAX_ATTEMPTS - 1):  # later runs retry it
            with SessionLocal() as s:
                email.deliver_pending(mark_system(s))
        (row,) = _rows(kind="bill")
        assert row.status == EmailStatus.failed and row.attempts == email.MAX_ATTEMPTS
    finally:
        email.set_transport(None)


def test_without_an_api_key_emails_wait_in_the_outbox(client, shop_a, cat):
    email.set_transport(None)
    _settings(client, shop_a, report_email=OWNER_EMAIL, email_each_bill=True)
    d = FakeDevice(client, shop_a)
    assert d.sync([d.bill([("Masala tea", 1, [])])]).status_code == 200
    (row,) = _rows(kind="bill")
    assert row.status == EmailStatus.pending and row.attempts == 0


# ---------------------------------------------------------------- shops are separate
def test_a_shop_never_delivers_another_shops_email(client, shop_a, shop_b, sent):
    build_catalogue(client, shop_a)
    build_catalogue(client, shop_b)
    for shop in (shop_a, shop_b):
        _settings(
            client,
            shop,
            report_email=f"{shop.shop.name.split()[-1].lower()}@example.com",
            email_each_bill=True,
        )
    email.set_transport(None)  # A's email waits
    a = FakeDevice(client, shop_a)
    a.sync([a.bill([("Masala tea", 1, [])])])
    email.set_transport(sent)
    b = FakeDevice(client, shop_b)
    b.sync([b.bill([("Masala tea", 1, [])])])
    assert [m.to for m in sent.messages] == ["b@example.com"]


# ---------------------------------------------------------------- day end
def test_closing_the_day_emails_the_variance_report(client, shop_a, cat, sent):
    _settings(client, shop_a, report_email=OWNER_EMAIL)
    h = shop_a.owner_h
    client.post(
        "/api/v1/stock-in",
        json={"ingredient_id": cat.milk["id"], "loose_qty": "1000", "cost_paise": 5600},
        headers=h,
    )
    day = business_date(utcnow()).isoformat()
    count = {"lines": [{"ingredient_id": cat.milk["id"], "loose_qty": "900"}]}
    # Twice: a cashier-style count is sent back once for a recount when off.
    for _ in range(2):
        client.post(f"/api/v1/day-counts/{day}/counts", json=count, headers=h)
    assert client.post(f"/api/v1/day-counts/{day}/approve", headers=h).status_code == 200
    (m,) = sent.messages
    assert m.subject.startswith("Day end ") and "₹5.60 missing" in m.subject  # 100 ml x 5.6 p
    assert "Milk" in m.text


# ---------------------------------------------------------------- daily cron
def _cron(client, today=None, token="s3cret"):
    q = f"?today={today.isoformat()}" if today else ""
    return client.get(f"/api/v1/cron/daily{q}", headers={"Authorization": f"Bearer {token}"})


def test_cron_refuses_without_the_secret(client, monkeypatch):
    assert _cron(client).status_code == 401  # no secret configured: always refused
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    assert _cron(client, token="guess").status_code == 401
    assert client.get("/api/v1/cron/daily").status_code == 401


def test_daily_summary_and_monday_export(client, shop_a, cat, sent, monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    _settings(client, shop_a, report_email=OWNER_EMAIL)
    d = FakeDevice(client, shop_a)
    yesterday_noon = datetime.now(UTC) - timedelta(days=1)
    bills = [
        d.bill([("Masala tea", 3, [])], sold_at=yesterday_noon),
        d.bill([("Orange juice", 1, [])], sold_at=yesterday_noon, payment_mode="upi"),
    ]
    assert {r["status"] for r in d.sync(bills).json()["results"]} == {"accepted"}
    yday = business_date(yesterday_noon)
    today = yday + timedelta(days=1)

    r = _cron(client, today).json()
    assert r["sent"] >= 1
    daily = [m for m in sent.messages if m.subject.startswith("Sales ")]
    assert len(daily) == 1
    assert daily[0].subject.endswith("₹120 from 2 bills")
    assert "Cash: ₹60" in daily[0].text and "UPI: ₹60" in daily[0].text

    # Same day again (Vercel retries): nothing new.
    _cron(client, today)
    assert len([m for m in sent.messages if m.subject.startswith("Sales ")]) == 1

    # The Monday after: last week's data, as CSV files.
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    if not (monday - timedelta(days=7) <= yday <= monday - timedelta(days=1)):
        monday -= timedelta(days=7)
    _cron(client, monday)
    (weekly,) = [m for m in sent.messages if m.subject.startswith("Weekly data")]
    files = {
        a["filename"]: base64.b64decode(a["content"]).decode("utf-8-sig")
        for a in weekly.attachments
    }
    assert set(files) == {"bills.csv", "bill_lines.csv", "stock_movements.csv", "wastage.csv"}
    invoices = [row["invoice_no"] for row in csv.DictReader(io.StringIO(files["bills.csv"]))]
    assert sorted(invoices) == sorted(b["invoice_no"] for b in bills)


# ---------------------------------------------------------------- test button
def test_test_email_button(client, shop_a, sent):
    h = shop_a.owner_h
    assert client.post("/api/v1/shop/test-email", headers=h).status_code == 422  # no address
    _settings(client, shop_a, report_email=OWNER_EMAIL)
    assert client.post("/api/v1/shop/test-email", headers=h).json() == {
        "status": "sent",
        "to": OWNER_EMAIL,
    }
    assert sent.messages[0].to == OWNER_EMAIL
    assert client.post("/api/v1/shop/test-email", headers=shop_a.cashier_h).status_code == 403
    email.set_transport(None)
    assert client.post("/api/v1/shop/test-email", headers=h).json()["status"] == "waiting"

"""UPI match, the bill trail, the day's changes, the database refusing to edit a bill, and the
GST registration watch (services/upimatch.py, trail.py, gstwatch.py)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Payment
from tests.conftest import FakeDevice, build_catalogue

API = "/api/v1"


@pytest.fixture
def device(client, shop_a):
    build_catalogue(client, shop_a)
    return FakeDevice(client, shop_a)


def _sync(device, *bills):
    for r in device.sync(list(bills)).json()["results"]:
        assert r["status"] == "accepted", r


def _pay(shop, bill, status="paid", paid=None, method="upi"):
    db = mark_system(SessionLocal())
    total = db.execute(
        text("SELECT total_paise FROM bills WHERE id=:i"), {"i": bill["id"]}
    ).scalar()
    db.add(
        Payment(
            shop_id=shop.shop.id,
            bill_id=uuid.UUID(bill["id"]),
            method=method,
            status=status,
            amount_paise=total,
            paid_paise=paid if paid is not None else (total if status == "paid" else None),
            provider_order_id=f"order_{uuid.uuid4().hex[:14]}",
            provider_payment_id=f"pay_{uuid.uuid4().hex[:14]}" if status == "paid" else None,
            created_by=shop.owner.id,
            paid_at=datetime.now(UTC) if status == "paid" else None,
        )
    )
    db.commit()
    db.close()


def _match(client, shop):
    return client.get(f"{API}/reports/upi-match", headers=shop.owner_h).json()


# ---------------------------------------------------------------- UPI match
def test_a_upi_bill_with_no_confirmed_payment_is_listed_against_the_cashier(client, shop_a, device):
    ok = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    ghost = device.bill([("Orange juice", 1, [])], payment_mode="upi")
    cash = device.bill([("Masala tea", 1, [])], payment_mode="cash")
    _sync(device, ok, ghost, cash)
    _pay(shop_a, ok)
    m = _match(client, shop_a)
    assert m["online_on"] is True
    assert m["upi_bills"] == 2 and m["upi_billed_paise"] == 2000 + 6000
    assert m["confirmed_paise"] == 2000
    (miss,) = m["unconfirmed"]
    assert miss["bill_id"] == ghost["id"] and miss["upi_paise"] == 6000 and miss["state"] == "none"
    assert miss["cashier"] == "Shop A cashier"
    (who,) = m["by_cashier"]
    assert who["upi_bills"] == 2 and who["unconfirmed"] == 1 and who["unconfirmed_paise"] == 6000


def test_a_failed_attempt_is_not_money_and_a_split_counts_only_its_upi_part(client, shop_a, device):
    failed = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    split = device.bill(
        [("Orange juice", 1, [])], payment_mode="split", parts=[("cash", 1000), ("upi", 5000)]
    )
    _sync(device, failed, split)
    _pay(shop_a, failed, status="failed")
    _pay(shop_a, split, paid=5000)
    m = _match(client, shop_a)
    assert [u["bill_id"] for u in m["unconfirmed"]] == [failed["id"]]
    assert m["unconfirmed"][0]["state"] == "failed"
    assert m["upi_billed_paise"] == 2000 + 5000 and m["confirmed_paise"] == 5000
    assert m["differs"] == []


def test_a_different_amount_and_money_for_a_voided_bill_are_flagged(client, shop_a, device):
    short = device.bill([("Orange juice", 1, [])], payment_mode="upi")
    gone = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    _sync(device, short, gone)
    _pay(shop_a, short, paid=5000)
    _pay(shop_a, gone)
    client.post(
        f"{API}/bills/{gone['id']}/void", json={"reason": "duplicate"}, headers=shop_a.owner_h
    ).raise_for_status()
    m = _match(client, shop_a)
    (d,) = m["differs"]
    assert d["upi_paise"] == 6000 and d["paid_paise"] == 5000
    (v,) = m["paid_for_void"]
    assert v["bill_id"] == gone["id"] and v["paid_paise"] == 2000
    assert m["unconfirmed"] == []


def test_without_razorpay_the_check_says_it_has_nothing_to_compare(client, shop_a, device):
    _sync(device, device.bill([("Masala tea", 1, [])], payment_mode="upi"))
    m = _match(client, shop_a)
    assert m["online_on"] is False and len(m["unconfirmed"]) == 1


def test_the_upi_match_is_owner_only_and_per_shop(client, shop_a, shop_b, device):
    _sync(device, device.bill([("Masala tea", 1, [])], payment_mode="upi"))
    assert client.get(f"{API}/reports/upi-match", headers=shop_a.cashier_h).status_code == 403
    assert client.get(f"{API}/reports/upi-match").status_code == 401
    assert _match(client, shop_b)["upi_bills"] == 0
    bad = client.get(
        f"{API}/reports/upi-match?from=2026-01-01&to=2026-06-01", headers=shop_a.owner_h
    )
    assert bad.status_code == 422


# ---------------------------------------------------------------- the trail and the changes
def test_a_bills_trail_tells_who_discounted_it_and_who_voided_it(client, shop_a, device):
    b = device.bill(
        [("Masala tea", 2, [])],
        bill_discount=300,
        reason="",
        sold_at=datetime.now(UTC) - timedelta(hours=3),
    )
    _sync(device, b)
    client.post(
        f"{API}/bills/{b['id']}/void",
        json={"reason": "customer_cancelled", "note": "left without paying"},
        headers=shop_a.owner_h,
    ).raise_for_status()
    t = client.get(f"{API}/bills/{b['id']}/trail", headers=shop_a.owner_h).json()
    kinds = [f["kind"] for f in t["facts"]]
    assert kinds[0] == "sold" and "late" in kinds and "discount" in kinds and kinds[-1] == "void"
    sold = t["facts"][0]
    assert sold["by"] == "Shop A cashier" and sold["amount_paise"] == b["totals"]["total"]
    disc = next(f for f in t["facts"] if f["kind"] == "discount")
    assert disc["amount_paise"] == 300 and disc["detail"] == "No reason written"
    void = t["facts"][-1]
    assert "customer cancelled" in void["detail"] and "left without paying" in void["detail"]
    assert void["by"] == "Shop A owner" and "stock came back" in void["detail"]
    assert client.get(f"{API}/bills/{b['id']}/trail", headers=shop_a.cashier_h).status_code == 403


def test_the_days_changes_lists_voids_discounts_and_cancelled_items(client, shop_a, device):
    plain = device.bill([("Masala tea", 1, [])])
    off = device.bill([("Orange juice", 1, [])], bill_discount=200, reason="Regular")
    _sync(device, plain, off)
    client.post(
        f"{API}/bills/{plain['id']}/void", json={"reason": "wrong_item"}, headers=shop_a.owner_h
    ).raise_for_status()
    r = client.get(f"{API}/reports/changes", headers=shop_a.owner_h).json()
    assert r["counts"] == {"void": 1, "discount": 1}
    void = next(x for x in r["rows"] if x["kind"] == "void")
    assert void["bill_id"] == plain["id"] and void["amount_paise"] == 2000
    assert void["by"] == "Shop A owner"
    disc = next(x for x in r["rows"] if x["kind"] == "discount")
    assert disc["amount_paise"] == 200 and disc["detail"] == "Regular"
    assert client.get(f"{API}/reports/changes", headers=shop_a.cashier_h).status_code == 403


# ---------------------------------------------------------------- the database refuses edits
def _sql(sql, **params):
    db = mark_system(SessionLocal())
    try:
        db.execute(text(sql), params)
        db.commit()
    finally:
        db.rollback()
        db.close()


def test_the_database_refuses_to_edit_or_delete_a_bill(client, shop_a, device):
    b = device.bill([("Masala tea", 1, [])])
    _sync(device, b)
    with pytest.raises(DBAPIError, match="cannot be edited"):
        _sql("UPDATE bills SET total_paise = 1 WHERE id = :i", i=b["id"])
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        _sql("DELETE FROM bills WHERE id = :i", i=b["id"])
    with pytest.raises(DBAPIError, match="cannot be edited"):  # voiding while changing a field
        _sql("UPDATE bills SET status='void', total_paise = 1 WHERE id = :i", i=b["id"])


def test_a_void_still_works_and_cannot_be_undone_or_rewritten(client, shop_a, device):
    b = device.bill([("Masala tea", 1, [])])
    _sync(device, b)
    r = client.post(f"{API}/bills/{b['id']}/void", json={"reason": "other"}, headers=shop_a.owner_h)
    assert r.status_code == 200 and r.json()["status"] == "void"
    with pytest.raises(DBAPIError, match="cannot be edited"):  # void back to completed
        _sql("UPDATE bills SET status='completed' WHERE id = :i", i=b["id"])
    with pytest.raises(DBAPIError, match="append-only"):
        _sql("UPDATE bill_voids SET note='nothing happened' WHERE bill_id = :i", i=b["id"])
    with pytest.raises(DBAPIError, match="append-only"):
        _sql("DELETE FROM bill_voids WHERE bill_id = :i", i=b["id"])


# ---------------------------------------------------------------- GST registration watch
def _set(client, shop, **body):
    r = client.patch(f"{API}/shop", json=body, headers=shop.owner_h)
    assert r.status_code == 200, r.text


def test_a_registered_shop_just_sees_its_turnover(client, shop_a, device):
    _sync(device, device.bill([("Masala tea", 1, [])]))
    g = client.get(f"{API}/reports/gst-watch", headers=shop_a.owner_h).json()
    assert g["status"] == "registered" and g["turnover_paise"] == 1904  # 20.00 less 5% inclusive


def test_an_unregistered_shop_has_no_watch_until_the_owner_types_a_limit(client, shop_a, device):
    _set(client, shop_a, gst_type="unregistered")
    _sync(device, device.bill([("Masala tea", 1, [])]))
    g = client.get(f"{API}/reports/gst-watch", headers=shop_a.owner_h).json()
    assert g["status"] == "no_threshold" and g["threshold_paise"] is None


def test_the_watch_moves_from_safe_to_watch_to_over(client, shop_a, device):
    _set(client, shop_a, gst_type="unregistered")
    _sync(device, device.bill([("Masala tea", 1, [])]))
    got = lambda: client.get(f"{API}/reports/gst-watch", headers=shop_a.owner_h).json()  # noqa: E731
    _set(client, shop_a, gst_threshold_paise=100_000_000)  # Rs 10 lakh: far away
    far = got()
    assert far["status"] == "safe" and far["percent"] == 0 and far["turnover_paise"] == 1904
    _set(client, shop_a, gst_threshold_paise=2000)  # Rs 20: 95% used
    assert got()["status"] == "watch" and got()["percent"] == 95
    _set(client, shop_a, gst_threshold_paise=1904)
    over = got()
    assert over["status"] == "over" and over["cross_on"] is None
    _set(client, shop_a, gst_threshold_paise=None)
    assert got()["status"] == "no_threshold"


def test_voided_bills_do_not_count_toward_turnover(client, shop_a, device):
    b = device.bill([("Masala tea", 1, [])])
    _sync(device, b, device.bill([("Orange juice", 1, [])]))
    client.post(f"{API}/bills/{b['id']}/void", json={"reason": "other"}, headers=shop_a.owner_h)
    g = client.get(f"{API}/reports/gst-watch", headers=shop_a.owner_h).json()
    assert g["turnover_paise"] == 5714  # only the juice: 60.00 less 5% inclusive
    assert client.get(f"{API}/reports/gst-watch", headers=shop_a.cashier_h).status_code == 403


# ---------------------------------------------------------------- they reach the needs-you list
def _alerts(client, shop):
    r = client.get(f"{API}/reports/alerts", headers=shop.owner_h)
    return {a["kind"]: a for a in r.json()["alerts"]}


def test_unconfirmed_upi_and_the_gst_limit_reach_the_alerts(client, shop_a, device):
    first = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    second = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    real = device.bill([("Orange juice", 1, [])], payment_mode="upi")
    _sync(device, first, second, real)
    _pay(shop_a, real)  # Razorpay is in use, so the unconfirmed two stand out
    _set(client, shop_a, gst_type="unregistered", gst_threshold_paise=5000)
    got = _alerts(client, shop_a)
    assert "2 UPI bills" in got["upi_unconfirmed"]["title"]
    assert (
        got["upi_unconfirmed"]["urgency"] == "look"
        and "₹40 billed" in got["upi_unconfirmed"]["detail"]
    )
    assert got["gst_over"]["urgency"] == "act"
    assert "registration limit" in got["gst_over"]["title"]


def test_one_odd_upi_bill_or_a_registered_shop_makes_no_noise(client, shop_a, device):
    one = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    real = device.bill([("Orange juice", 1, [])], payment_mode="upi")
    _sync(device, one, real)
    _pay(shop_a, real)
    got = _alerts(client, shop_a)
    assert "upi_unconfirmed" not in got and "gst_over" not in got and "gst_watch" not in got

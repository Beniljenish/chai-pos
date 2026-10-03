"""Edge cases for bill sync: totals mismatch, clocks, invoice numbers, IST
midnight, financial years, recipe pinning, atomicity, cross-shop attempts."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.billing import consumption_for_line, financial_year, invoice_number
from tests.conftest import FakeDevice, build_catalogue

D = Decimal


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


@pytest.fixture
def device(client, shop_a, cat):
    return FakeDevice(client, shop_a)


def _one(device, bill):
    r = device.sync([bill])
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


# ---------- pure helpers ----------
@pytest.mark.parametrize(
    ("d", "fy"),
    [
        (date(2026, 10, 3), "26-27"),
        (date(2027, 3, 31), "26-27"),
        (date(2027, 4, 1), "27-28"),
        (date(2099, 12, 31), "99-00"),
    ],
)
def test_financial_year(d, fy):
    assert financial_year(d) == fy


def test_invoice_number_fits_gst_16_char_limit():
    assert invoice_number("C9", "26-27", 999_999) == "C9/26-27/999999"
    assert len(invoice_number("C99", "26-27", 999_999)) <= 16


def test_consumption_scales_then_adds_deltas_and_never_goes_negative():
    milk, sugar, cups = uuid4(), uuid4(), uuid4()
    recipe = {milk: D(100), cups: D(1)}
    mods = [
        {"scale_factor": D("1.5"), "lines": []},
        {
            "scale_factor": D(1),
            "lines": [
                {"ingredient_id": sugar, "qty_delta": D(-5)},
                {"ingredient_id": milk, "qty_delta": D(10)},
            ],
        },
    ]
    assert consumption_for_line(recipe, 2, mods) == {milk: D("320.000"), cups: D("3.000")}


# ---------- accept-and-flag ----------
def test_mismatched_totals_are_accepted_as_printed_and_flagged(client, shop_a, device):
    bill = device.bill([("Masala tea", 1, [])])
    bill["totals"]["total"] += 100  # device printed Rs 21 for a Rs 20 tea
    bill["totals"]["subtotal"] += 100
    res = _one(device, bill)
    assert res["status"] == "accepted" and res["totals_mismatch"] is True

    stored = client.get(f"/api/v1/bills/{bill['id']}", headers=shop_a.owner_h).json()
    assert stored["total_paise"] == 2100  # the books record what the customer was given
    assert stored["server_totals"]["total"] == 2000  # alongside what it should have been
    flagged = client.get("/api/v1/bills?mismatch_only=true", headers=shop_a.owner_h).json()
    assert [b["id"] for b in flagged] == [bill["id"]]


def test_registration_change_while_offline_is_flagged(client, shop_a, device):
    bill = device.bill([("Masala tea", 1, [])])  # printed as a regular-GST tax invoice
    client.patch("/api/v1/shop", json={"gst_type": "composition"}, headers=shop_a.owner_h)
    assert _one(device, bill)["totals_mismatch"] is True


# ---------- clocks, dates, numbering ----------
def test_device_clock_far_ahead_or_bill_too_old_is_rejected(device):
    ahead = device.bill([("Masala tea", 1, [])], sold_at=datetime.now(UTC) + timedelta(minutes=20))
    assert _one(device, ahead)["reason"] == "device_clock_ahead"
    old = device.bill([("Masala tea", 1, [])], sold_at=datetime.now(UTC) - timedelta(days=40))
    assert _one(device, old)["reason"] == "bill_too_old"


def test_business_date_is_shop_local_not_utc(client, shop_a, device):
    # 18:40 UTC yesterday = 00:10 IST today: it belongs to TODAY's business day.
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    sold = datetime(yesterday.year, yesterday.month, yesterday.day, 18, 40, tzinfo=UTC)
    bill = device.bill([("Masala tea", 1, [])], sold_at=sold)
    _one(device, bill)
    stored = client.get(f"/api/v1/bills/{bill['id']}", headers=shop_a.owner_h).json()
    assert stored["business_date"] == (yesterday + timedelta(days=1)).isoformat()


def test_wrong_invoice_number_is_rejected(device):
    bill = device.bill([("Masala tea", 1, [])])
    bill["invoice_no"] = "C1/26-27/000777"
    assert _one(device, bill)["reason"].startswith("invoice_no_mismatch")


def test_same_sequence_number_twice_is_rejected(device):
    first = device.bill([("Masala tea", 1, [])], seq=5)
    second = device.bill([("Masala tea", 2, [])], seq=5)  # different id, same slot
    assert _one(device, first)["status"] == "accepted"
    assert _one(device, second)["reason"] == "invoice_number_already_used"


def test_naive_timestamps_are_refused(device):
    bill = device.bill([("Masala tea", 1, [])])
    bill["sold_at"] = "2026-10-03T10:00:00"  # no timezone: ambiguous
    assert device.sync([bill]).status_code == 422


# ---------- stock ----------
def test_bill_deducts_with_the_recipe_version_it_was_sold_under(client, shop_a, cat, device):
    bill = device.bill([("Masala tea", 2, [])])  # device cached v1: 100 ml decoction
    client.put(
        f"/api/v1/menu-items/{cat.tea['id']}/recipe",
        json={"lines": [{"ingredient_id": cat.decoction["id"], "qty": "150"}]},
        headers=shop_a.owner_h,
    )
    _one(device, bill)  # synced after the edit
    rows = client.get(f"/api/v1/stock/{cat.decoction['id']}/ledger", headers=shop_a.owner_h).json()
    assert [r["qty_delta"] for r in rows if r["reason"] == "sale"] == ["-200.000"]


def test_one_bad_bill_does_not_block_or_half_save_the_batch(client, shop_a, cat, device):
    good1 = device.bill([("Masala tea", 1, [])])
    bad = device.bill([("Masala tea", 1, [])])
    bad["lines"][0]["menu_item_id"] = str(uuid4())
    good2 = device.bill([("Orange juice", 1, [])])
    results = device.sync([good1, bad, good2]).json()["results"]
    assert [r["status"] for r in results] == ["accepted", "rejected", "accepted"]
    assert results[1]["reason"] == "unknown_menu_item"
    ledger = client.get(
        f"/api/v1/stock/{cat.decoction['id']}/ledger", headers=shop_a.owner_h
    ).json()
    assert {r["ref_id"] for r in ledger} == {good1["id"]}


def test_recipe_of_another_item_is_rejected(cat, device):
    bill = device.bill([("Masala tea", 1, [])])
    juice = next(m for m in device.catalogue["menu_items"] if m["name"] == "Orange juice")
    bill["lines"][0]["recipe_id"] = juice["recipe"]["id"]
    assert _one(device, bill)["reason"] == "recipe_not_for_menu_item"


# ---------- access ----------
def test_cashier_sees_only_today_owner_can_choose(client, shop_a, device):
    _one(device, device.bill([("Masala tea", 1, [])]))
    old = device.bill([("Masala tea", 1, [])], sold_at=datetime.now(UTC) - timedelta(days=3))
    _one(device, old)
    day = old["sold_at"][:10]
    owner = client.get(f"/api/v1/bills?business_date={day}", headers=shop_a.owner_h).json()
    assert [b["id"] for b in owner] == [old["id"]]
    cashier = client.get(f"/api/v1/bills?business_date={day}", headers=shop_a.cashier_h).json()
    assert old["id"] not in [b["id"] for b in cashier]


def test_deactivated_device_cannot_sync(client, shop_a, device):
    client.patch(
        f"/api/v1/devices/{shop_a.device.id}", json={"is_active": False}, headers=shop_a.owner_h
    )
    assert device.sync([device.bill([("Masala tea", 1, [])])]).status_code == 403


def test_cross_shop_attempts(client, shop_a, shop_b, cat, device):
    build_catalogue(client, shop_b)
    device_b = FakeDevice(client, shop_b)
    b_bill = device_b.bill([("Masala tea", 1, [])])
    assert _one(device_b, b_bill)["status"] == "accepted"

    # A's device id belongs to A: shop B can't sync through it
    assert device.sync([b_bill], headers=shop_b.cashier_h).status_code == 404
    # A's bill using B's menu item
    mine = device.bill([("Masala tea", 1, [])])
    mine["lines"][0]["menu_item_id"] = device_b.catalogue["menu_items"][0]["id"]
    assert _one(device, mine)["reason"] == "unknown_menu_item"
    # A's bill reusing B's bill id: refused without revealing anything about it
    clash = device.bill([("Masala tea", 1, [])])
    clash["id"] = b_bill["id"]
    assert _one(device, clash)["reason"] == "id_conflict"
    assert client.get(f"/api/v1/bills/{b_bill['id']}", headers=shop_a.owner_h).status_code == 404
    assert client.get(f"/api/v1/bills/{b_bill['id']}", headers=shop_b.owner_h).status_code == 200

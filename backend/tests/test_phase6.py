"""Phase 6: discounts, split payment, customers and credit (khata), split bills.

Bills are still accepted and flagged, never refused, for anything a tablet could
have done offline: a discount over the cashier's limit, payment parts that do not
add up, credit with no customer."""

import uuid

import pytest

from app.services.billing import content_hash
from tests.conftest import FakeDevice, build_catalogue
from tests.test_shifts import _day, _open, _report
from tests.test_shifts import _sync as _sync_shifts

API = "/api/v1"
PRIYA = {"phone": "9876543210", "name": "Priya"}


@pytest.fixture
def device(client, shop_a):
    build_catalogue(client, shop_a)
    return FakeDevice(client, shop_a)


def _accept(device, bill, headers=None):
    r = device.sync([bill], headers=headers).json()["results"][0]
    assert r["status"] == "accepted", r
    return r


def _bill(client, shop, bill_id):
    return client.get(f"{API}/bills/{bill_id}", headers=shop.owner_h).json()


def _sales(client, shop):
    return client.get(f"{API}/reports/sales", headers=shop.owner_h).json()


def _customer(**kw):
    return {"id": str(uuid.uuid4()), **PRIYA, **kw}


# ---------------------------------------------------------------- discounts
def test_discounts_are_priced_like_the_tablet_and_recorded(client, shop_a, device):
    # Two teas (40) and a juice (60): 4 off the teas, then 5 off the bill (9% in all,
    # inside the cashier's default 10%). The 5 is shared 1.875 : 3.125, so 188 + 312.
    b = device.bill(
        [("Masala tea", 2, []), ("Orange juice", 1, [])],
        line_discounts={0: 400},
        bill_discount=500,
        reason="Regular customer",
    )
    r = _accept(device, b)
    assert r["totals_mismatch"] is False  # the server prices discounts the same way
    got = _bill(client, shop_a, b["id"])
    assert got["discount_paise"] == 900 and got["total_paise"] == 9100
    assert got["discount_reason"] == "Regular customer"
    assert [ln["discount_paise"] for ln in got["lines"]] == [400 + 188, 312]
    assert got["flags"] == []

    rep = _sales(client, shop_a)
    assert rep["discount_paise"] == 900
    (d,) = rep["discounts"]
    assert d["invoice_no"] == b["invoice_no"] and d["reason"] == "Regular customer"
    assert d["over_limit"] is False


def test_a_cashier_over_the_limit_is_flagged_not_refused(client, shop_a, device):
    client.patch(
        f"{API}/shop", json={"max_discount_bp": 1000}, headers=shop_a.owner_h
    ).raise_for_status()
    device.refresh_catalogue()
    assert device.catalogue["shop"]["max_discount_bp"] == 1000
    big = device.bill([("Masala tea", 5, [])], bill_discount=2500, reason="friend")  # 25%
    _accept(device, big)
    assert _bill(client, shop_a, big["id"])["flags"] == ["discount_over_limit"]
    # The owner may give any discount.
    mine = device.bill([("Masala tea", 5, [])], bill_discount=2500, reason="staff meal")
    _accept(device, mine, headers=shop_a.owner_h)
    assert _bill(client, shop_a, mine["id"])["flags"] == []
    # A discount with no reason is flagged too (the app always asks for one).
    quiet = device.bill([("Masala tea", 1, [])], bill_discount=100)
    _accept(device, quiet, headers=shop_a.owner_h)
    assert _bill(client, shop_a, quiet["id"])["flags"] == ["discount_without_reason"]
    assert [d["over_limit"] for d in _sales(client, shop_a)["discounts"]] == [
        True,
        False,
        False,
    ]
    # Only the owner sets the limit.
    r = client.patch(f"{API}/shop", json={"max_discount_bp": 9000}, headers=shop_a.cashier_h)
    assert r.status_code == 403


def test_an_old_tablet_resending_a_bill_still_hashes_the_same(client, shop_a, device):
    """Bills from before Phase 6 carry none of its keys: a retry must stay a
    harmless duplicate, so the new keys are left out of the hash when unused."""
    from app.api.v1.bills import _as_received
    from app.schemas_billing import SyncBillIn

    b = device.bill([("Masala tea", 1, [])])
    assert content_hash(_as_received(SyncBillIn.model_validate(b))) == content_hash(
        _as_received_before_phase6(SyncBillIn.model_validate(b))
    )
    _accept(device, b)
    assert device.sync([b]).json()["results"][0]["status"] == "duplicate"


def _as_received_before_phase6(model) -> dict:
    """What the server hashed before Phase 6 (the keys it knew then)."""
    d = model.model_dump()
    for key in ("cashier_id", "shift_id", "order_id"):
        if d.get(key) is None:
            d.pop(key, None)
    new_bill_keys = (
        "bill_discount_paise",
        "discount_reason",
        "payment_parts",
        "customer",
        "order_part",
    )
    for key in new_bill_keys:
        d.pop(key, None)
    d["totals"].pop("discount", None)
    for ln in d["lines"]:
        ln.pop("discount_paise", None)
        ln["totals"].pop("discount", None)
    return d


# ---------------------------------------------------------------- split payment
def test_split_payment_counts_each_part_where_it_belongs(client, shop_a, device):
    h = shop_a.cashier_h
    sid = uuid.uuid4()
    assert _sync_shifts(client, h, device.device_id, [_open(sid)]) == [("accepted", None)]
    b = device.bill(
        [("Orange juice", 1, [])], payment_mode="split", parts=[("cash", 2000), ("upi", 4000)]
    )
    b["shift_id"] = str(sid)
    # No discount on it: the totals still match (a missing "discount" means 0).
    assert _accept(device, b)["totals_mismatch"] is False
    got = _bill(client, shop_a, b["id"])
    assert got["payment_parts"] == [{"mode": "cash", "paise": 2000}, {"mode": "upi", "paise": 4000}]
    assert got["flags"] == []
    modes = {m["mode"]: m["total_paise"] for m in _sales(client, shop_a)["by_mode"]}
    assert modes == {"cash": 2000, "upi": 4000}
    (s,) = _report(client, shop_a.owner_h)["shifts"]
    assert s["cash_paise"] == 2000 and s["upi_paise"] == 4000
    assert s["expected_cash_paise"] == 50000 + 2000

    wrong = device.bill(
        [("Masala tea", 1, [])], payment_mode="split", parts=[("cash", 500), ("upi", 500)]
    )
    _accept(device, wrong)
    assert _bill(client, shop_a, wrong["id"])["flags"] == ["payment_parts_mismatch"]


# ---------------------------------------------------------------- customers and credit
def test_credit_builds_a_khata_that_repayments_bring_down(client, shop_a, device):
    h = shop_a.cashier_h
    first = device.bill([("Masala tea", 2, [])], payment_mode="credit", customer=_customer())
    _accept(device, first)
    # Another tablet, offline, made its own customer record for the same number.
    second = device.bill(
        [("Orange juice", 1, [])],
        payment_mode="split",
        parts=[("cash", 1000), ("credit", 5000)],
        customer=_customer(name="Priya S"),
    )
    _accept(device, second)

    (found,) = client.get(f"{API}/customers?q=98765", headers=h).json()["customers"]
    assert found["name"] == "Priya S" and found["outstanding_paise"] == 4000 + 5000
    assert (
        client.get(f"{API}/customers?q=Pri", headers=h).json()["customers"][0]["id"] == found["id"]
    )
    cid = found["id"]
    detail = client.get(f"{API}/customers/{cid}", headers=h).json()
    assert [v["invoice_no"] for v in detail["visits"]] == [
        second["invoice_no"],
        first["invoice_no"],
    ]
    assert [v["credit_paise"] for v in detail["visits"]] == [5000, 4000]

    pay = {"id": str(uuid.uuid4()), "amount_paise": 3000, "mode": "cash", "note": ""}
    r = client.post(f"{API}/customers/{cid}/repayments", json=pay, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["outstanding_paise"] == 6000
    # The same repayment sent twice (a retry) is recorded once.
    assert (
        client.post(f"{API}/customers/{cid}/repayments", json=pay, headers=h).json()[
            "outstanding_paise"
        ]
        == 6000
    )
    too_much = {"id": str(uuid.uuid4()), "amount_paise": 6001, "mode": "upi", "note": ""}
    r = client.post(f"{API}/customers/{cid}/repayments", json=too_much, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "more_than_owed"

    # A voided credit bill is no longer owed.
    client.post(
        f"{API}/bills/{first['id']}/void", json={"reason": "duplicate"}, headers=shop_a.owner_h
    ).raise_for_status()
    detail = client.get(f"{API}/customers/{cid}", headers=h).json()
    assert detail["outstanding_paise"] == 5000 - 3000

    # The owner's khata: everyone who owes, biggest first. Cashiers do not see it.
    assert client.get(f"{API}/reports/khata", headers=h).status_code == 403
    (k,) = client.get(f"{API}/reports/khata", headers=shop_a.owner_h).json()["customers"]
    assert k["id"] == cid and k["outstanding_paise"] == 2000

    rep = _sales(client, shop_a)
    assert rep["credit_given_paise"] == 5000  # the voided bill is out
    assert rep["repaid_paise"] == 3000


def test_cash_repayment_goes_into_the_drawer(client, shop_a, device):
    h = shop_a.cashier_h
    sid = uuid.uuid4()
    _sync_shifts(client, h, device.device_id, [_open(sid)])
    b = device.bill([("Masala tea", 1, [])], payment_mode="credit", customer=_customer())
    _accept(device, b)
    cid = client.get(f"{API}/customers?q=9876543210", headers=h).json()["customers"][0]["id"]
    pay = {"id": str(uuid.uuid4()), "amount_paise": 2000, "mode": "cash", "shift_id": str(sid)}
    client.post(f"{API}/customers/{cid}/repayments", json=pay, headers=h).raise_for_status()
    (s,) = _report(client, shop_a.owner_h)["shifts"]
    assert s["repaid_cash_paise"] == 2000
    assert s["expected_cash_paise"] == 50000 + 2000
    assert _day()  # same business day as the shift


def test_credit_without_a_customer_is_flagged(client, shop_a, device):
    b = device.bill([("Masala tea", 1, [])], payment_mode="credit")
    _accept(device, b)
    assert _bill(client, shop_a, b["id"])["flags"] == ["credit_without_customer"]


def test_customers_belong_to_one_shop(client, shop_a, shop_b, device):
    _accept(
        device, device.bill([("Masala tea", 1, [])], payment_mode="credit", customer=_customer())
    )
    assert client.get(f"{API}/customers?q=98765", headers=shop_b.owner_h).json()["customers"] == []


# ---------------------------------------------------------------- split bill
def test_one_order_split_into_two_invoices(client, shop_a, device):
    from tests.test_orders import _ev, _line
    from tests.test_orders import _sync as _sync_orders

    h = shop_a.cashier_h
    cat = build_catalogue  # noqa: F841  (catalogue already built by the fixture)
    oid = str(uuid.uuid4())
    tea = {
        "line_id": str(uuid.uuid4()),
        "menu_item_id": device.catalogue["menu_items"][0]["id"],
        "name": "Masala tea",
        "qty": 3,
        "unit_price_paise": 2000,
        "gst_rate_bp": 500,
        "tax_inclusive": True,
    }
    _ = _line
    _sync_orders(
        client,
        h,
        device.device_id,
        [
            _ev(oid, "open", {"order_type": "takeaway"}, -20),
            _ev(oid, "kot", {"kot_no": "C1-1", "lines": [tea]}, -19),
        ],
    )
    one = device.bill([("Masala tea", 2, [])])
    two = device.bill([("Masala tea", 1, [])], order_part=2)
    for b in (one, two):
        b["order_id"] = oid
    _sync_orders(
        client,
        h,
        device.device_id,
        [
            _ev(oid, "settle", {"bill_id": one["id"], "part": 1, "parts": 2}, -2),
        ],
    )
    live = {o["id"]: o for o in client.get(f"{API}/orders/live", headers=h).json()["orders"]}
    assert live[oid]["status"] == "billed"  # one of two parts paid: not done yet
    _sync_orders(
        client,
        h,
        device.device_id,
        [_ev(oid, "settle", {"bill_id": two["id"], "part": 2, "parts": 2}, -1)],
    )
    _accept(device, one)
    _accept(device, two)
    # Another tablet settling part 1 again is refused, as a whole-order settle was.
    again = device.bill([("Masala tea", 2, [])])
    again["order_id"] = oid
    r = device.sync([again]).json()["results"][0]
    assert r["status"] == "rejected" and r["reason"] == "order_already_billed"
    order = client.get(f"{API}/orders/{oid}", headers=shop_a.owner_h).json()
    assert order["status"] == "settled"
    assert sorted(order["state"]["bill_ids"]) == sorted([one["id"], two["id"]])


def test_the_daily_email_mentions_discounts_and_khata(client, shop_a, device):
    from app.core.time import business_date, utcnow
    from app.db.session import SessionLocal
    from app.db.tenancy import bind_tenant
    from app.services.reports import daily_figures

    _accept(device, device.bill([("Masala tea", 5, [])], bill_discount=2500, reason="friend"))
    _accept(
        device, device.bill([("Orange juice", 1, [])], payment_mode="credit", customer=_customer())
    )
    with SessionLocal() as s:
        bind_tenant(s, shop_a.shop.id)
        f = daily_figures(s, business_date(utcnow()))
    assert f["money"] == [
        "Discounts: ₹25 on 1 bill(s), 1 over the cashier limit",
        "Khata: ₹60 given on credit, ₹0 repaid",
    ]
    assert f["by_mode"] == {"cash": 7500, "credit": 6000}

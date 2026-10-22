# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Outlet statements, the operator's fee, automatic refunds for a cancelled paid order, and the
UPI match leaving food-court orders alone (services/onlinepay.py, upimatch.py)."""

from datetime import date, timedelta

from tests.test_food_court import API, _events, _live, court  # noqa: F401
from tests.test_online_payments import TWO, _pay, _start, rzp  # noqa: F401


def _money(client, court):
    rows = client.get(f"{API}/platform/online-money", headers=court["admin"]).json()["outlets"]
    return {r["outlet"]: r for r in rows}


def _fee(client, court, outlet_id, bp):
    return client.patch(
        f"{API}/platform/courts/{court['id']}/outlets/{outlet_id}/fee",
        json={"fee_bp": bp},
        headers=court["admin"],
    )


def _range():
    today = date.today()
    return f"from={today - timedelta(days=1)}&to={today + timedelta(days=1)}"


def test_a_cancelled_paid_order_is_refunded_at_once(client, shop_a, shop_b, court, rzp):
    started = _start(client, court, TWO).json()
    _pay(client, rzp, started)
    live = _live(client, shop_a)[0]
    _events(client, shop_a, live["id"], [("cancel_order", {"reason": "out of milk"})])
    assert len(rzp.refunds) == 1 and rzp.refunds[0][0] == "pay_TEST0001"
    money = client.get(f"{API}/platform/online-money", headers=court["admin"]).json()
    assert money["refunds_due"] == []
    # syncing the same cancel again never refunds twice
    _events(client, shop_a, live["id"], [("cancel_order", {"reason": "again"})])
    assert len(rzp.refunds) == 1


def test_the_fee_is_taken_from_what_the_outlet_is_owed(client, shop_a, shop_b, court, rzp):
    started = _start(client, court, [("a", "Masala tea", 3)]).json()
    _pay(client, rzp, started)  # 3 teas: Rs 60 = 6000 paise
    row = _money(client, court)[shop_a.shop.name]
    assert row["paid_paise"] == 6000 and row["fee_paise"] == 0 and row["owed_paise"] == 6000
    assert _fee(client, court, row["outlet_id"], 550).status_code == 200  # 5.5%
    row = _money(client, court)[shop_a.shop.name]
    assert row["fee_bp"] == 550 and row["fee_paise"] == 330  # 6000 x 5.5% = 330
    assert row["net_paise"] == 5670 and row["owed_paise"] == 5670
    # settling is capped at what is owed after the fee
    url = f"{API}/platform/courts/{court['id']}/outlets/{row['outlet_id']}/settlements"
    over = client.post(url, json={"amount_paise": 5671}, headers=court["admin"])
    assert over.status_code == 409
    ok = client.post(url, json={"amount_paise": 5670}, headers=court["admin"])
    assert ok.status_code == 201
    assert _money(client, court)[shop_a.shop.name]["owed_paise"] == 0


def test_the_fee_rounds_half_up_per_order_and_is_capped(client, shop_a, court, rzp):
    from app.services.onlinepay import fee_of

    assert fee_of(2000, 250) == 50  # exact
    assert fee_of(1999, 250) == 50  # 49.975 -> 50
    assert fee_of(1, 5000) == 1  # 0.5 -> 1: half up
    assert fee_of(1, 4999) == 0
    row = _money(client, court)[shop_a.shop.name]
    assert _fee(client, court, row["outlet_id"], 3001).status_code == 422
    assert _fee(client, court, row["outlet_id"], -1).status_code == 422


def test_an_outlets_statement_adds_up_and_the_admin_sees_the_same(
    client, shop_a, shop_b, court, rzp
):
    started = _start(client, court, [("a", "Masala tea", 2), ("b", "Orange juice", 1)]).json()
    _pay(client, rzp, started)
    second = _start(client, court, [("a", "Masala tea", 1)]).json()
    _pay(client, rzp, second, payment_id="pay_TEST0002")
    outlet_id = _money(client, court)[shop_a.shop.name]["outlet_id"]
    _fee(client, court, outlet_id, 1000)  # 10%

    # one of the two orders is cancelled (and refunded)
    cancel = _live(client, shop_a)[0]
    _events(client, shop_a, cancel["id"], [("cancel_order", {"reason": "sold out"})])

    st = client.get(f"{API}/food-court/statement?{_range()}", headers=shop_a.owner_h).json()
    assert len(st["orders"]) == 2
    assert st["refunds_paise"] > 0 and st["sales_paise"] > 0
    assert st["fee_paise"] == st["sales_paise"] // 10  # 10% of what was really sold
    assert st["earned_paise"] == st["sales_paise"] - st["fee_paise"]
    assert st["owed_now_paise"] == st["earned_paise"]  # nothing paid out yet
    assert st["paid_out"] == [] and st["fee_bp"] == 1000
    assert sum(1 for o in st["orders"] if o["cancelled"]) == 1
    # pay some out: it shows in the statement and lowers what is owed
    url = f"{API}/platform/courts/{court['id']}/outlets/{outlet_id}/settlements"
    client.post(url, json={"amount_paise": 1000, "note": "UPI Monday"}, headers=court["admin"])
    st2 = client.get(f"{API}/food-court/statement?{_range()}", headers=shop_a.owner_h).json()
    assert st2["paid_out_paise"] == 1000 and st2["owed_now_paise"] == st["earned_paise"] - 1000
    admin_view = client.get(
        f"{API}/platform/courts/{court['id']}/outlets/{outlet_id}/statement?{_range()}",
        headers=court["admin"],
    ).json()
    assert admin_view["earned_paise"] == st2["earned_paise"]


def test_a_statement_is_for_the_outlets_owner_only(client, shop_a, shop_b, court):
    q = _range()
    assert client.get(f"{API}/food-court/statement?{q}").status_code == 401
    assert (
        client.get(f"{API}/food-court/statement?{q}", headers=shop_a.cashier_h).status_code == 403
    )
    too_long = "from=2026-01-01&to=2026-12-31"
    assert (
        client.get(f"{API}/food-court/statement?{too_long}", headers=shop_a.owner_h).status_code
        == 422
    )
    # only the super admin sets a fee, and an outlet owner's token is not an admin's
    outlet = client.get(f"{API}/food-court", headers=shop_a.owner_h).json()
    assert outlet["fee_bp"] == 0
    bad = client.patch(
        f"{API}/platform/courts/{court['id']}/outlets/{court['a']}/fee",
        json={"fee_bp": 900},
        headers=shop_a.owner_h,
    )
    assert bad.status_code == 401


def test_the_upi_match_leaves_an_order_paid_through_the_food_court_alone(
    client, shop_a, shop_b, court, rzp
):
    """The outlet bills a prepaid online order as UPI when it hands the food over; the customer's
    money went to the food court's account, so that bill is not a missing UPI payment."""
    from tests.conftest import FakeDevice

    started = _start(client, court, [("a", "Masala tea", 1)]).json()
    _pay(client, rzp, started)
    live = _live(client, shop_a)[0]
    device = FakeDevice(client, shop_a)
    bill = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    bill["order_id"] = live["id"]
    assert device.sync([bill]).json()["results"][0]["status"] == "accepted"
    plain = device.bill([("Masala tea", 1, [])], payment_mode="upi")
    device.sync([plain])
    m = client.get(f"{API}/reports/upi-match", headers=shop_a.owner_h).json()
    assert m["via_food_court_paise"] == 2000
    assert [u["bill_id"] for u in m["unconfirmed"]] == [plain["id"]]

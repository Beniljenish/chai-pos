"""Restaurant service: tables, running orders, and settling into an invoice."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services.orders import reduce
from tests.conftest import FakeDevice, build_catalogue

API = "/api/v1"
CASES = json.loads((Path(__file__).parents[2] / "shared" / "order_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_order_rules(case):
    """The same cases run in frontend/src/lib/orders.test.ts."""
    state = reduce(case["events"])
    assert {k: state[k] for k in case["expect"]} == case["expect"]


# ---------------------------------------------------------------- the API
def _at(minutes=0):
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def _ev(order_id, kind, data=None, minutes=0, by=None, eid=None):
    e = {
        "id": eid or str(uuid.uuid4()),
        "order_id": order_id,
        "kind": kind,
        "at": _at(minutes),
        "data": data or {},
    }
    if by:
        e["by"] = by
    return e


def _line(cat, qty=1, line_id=None):
    return {
        "line_id": line_id or str(uuid.uuid4()),
        "menu_item_id": cat.tea["id"],
        "name": "Masala tea",
        "qty": qty,
        "unit_price_paise": 2000,
        "gst_rate_bp": 500,
        "tax_inclusive": True,
    }


@pytest.fixture
def setup(client, shop_a):
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    hall = client.post(f"{API}/areas", json={"name": "Hall"}, headers=h).json()
    t1 = client.post(
        f"{API}/tables", json={"area_id": hall["id"], "name": "T1", "seats": 2}, headers=h
    ).json()
    t2 = client.post(f"{API}/tables", json={"area_id": hall["id"], "name": "T2"}, headers=h).json()
    device = FakeDevice(client, shop_a)
    return cat, device, t1, t2


def _sync(client, h, device_id, events):
    r = client.post(
        f"{API}/sync/orders", json={"device_id": str(device_id), "events": events}, headers=h
    )
    assert r.status_code == 200, r.text
    return [(x["status"], x["reason"]) for x in r.json()["results"]]


def _live(client, h):
    return {o["id"]: o for o in client.get(f"{API}/orders/live", headers=h).json()["orders"]}


def test_tables_reach_the_tablet_catalogue(client, shop_a, setup):
    cat_json = client.get(f"{API}/catalogue", headers=shop_a.cashier_h).json()
    (hall,) = cat_json["areas"]
    assert hall["name"] == "Hall" and [t["name"] for t in hall["tables"]] == ["T1", "T2"]
    assert hall["tables"][0]["seats"] == 2


def test_a_table_order_from_two_devices_settles_into_one_invoice(client, shop_a, setup):
    cat, device, t1, _ = setup
    h = shop_a.cashier_h
    oid = str(uuid.uuid4())
    l1 = _line(cat, 2)
    assert (
        _sync(
            client,
            h,
            device.device_id,
            [
                _ev(oid, "open", {"order_type": "dine_in", "table_id": t1["id"], "covers": 2}, -30),
                _ev(oid, "kot", {"kot_no": "C1-1", "lines": [l1]}, -29),
            ],
        )
        == [("accepted", None)] * 2
    )

    # A waiter's phone (a second device) adds a round to the same table.
    phone = client.post(
        f"{API}/devices", json={"name": "Waiter phone"}, headers=shop_a.owner_h
    ).json()
    _sync(
        client, h, phone["id"], [_ev(oid, "kot", {"kot_no": "C2-1", "lines": [_line(cat, 1)]}, -10)]
    )

    o = _live(client, h)[oid]
    assert o["status"] == "open" and o["table_id"] == t1["id"]
    assert [ln["qty"] for ln in o["state"]["lines"]] == [2, 1]
    assert [k["kot_no"] for k in o["state"]["kots"]] == ["C1-1", "C2-1"]

    _sync(client, h, device.device_id, [_ev(oid, "bill_printed", {}, -5)])
    assert _live(client, h)[oid]["status"] == "billed"

    # Settling: the invoice is an ordinary bill that names the order.
    bill = device.bill([("Masala tea", 3, [])])
    bill["order_id"] = oid
    _sync(client, h, device.device_id, [_ev(oid, "settle", {"bill_id": bill["id"]}, -1)])
    assert device.sync([bill]).json()["results"][0]["status"] == "accepted"
    assert client.get(f"{API}/bills/{bill['id']}", headers=shop_a.owner_h).json()["order_id"] == oid

    # Gone from the live floor, but a device that last looked earlier hears about it.
    assert oid not in _live(client, h)
    since = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    later = client.get(f"{API}/orders/live", params={"since": since}, headers=h).json()["orders"]
    assert [o["status"] for o in later if o["id"] == oid] == ["settled"]

    # A second tablet settling the same table is refused at the bill.
    twice = device.bill([("Masala tea", 3, [])])
    twice["order_id"] = oid
    res = device.sync([twice]).json()["results"][0]
    assert (res["status"], res["reason"]) == ("rejected", "order_already_billed")


def test_retries_are_harmless_and_bad_events_refused(client, shop_a, setup):
    cat, device, t1, _ = setup
    h = shop_a.cashier_h
    oid = str(uuid.uuid4())
    opened = _ev(oid, "open", {"order_type": "dine_in", "table_id": t1["id"]}, -5)
    assert _sync(client, h, device.device_id, [opened]) == [("accepted", None)]
    assert _sync(client, h, device.device_id, [opened]) == [("duplicate", None)]
    assert _sync(client, h, device.device_id, [{**opened, "data": {"order_type": "takeaway"}}]) == [
        ("rejected", "id_reused_with_different_content")
    ]
    assert _sync(
        client, h, device.device_id, [_ev(str(uuid.uuid4()), "move", {"table_id": None})]
    ) == [("rejected", "unknown_order")]
    assert _sync(client, h, device.device_id, [_ev(oid, "move", {"table_id": None}, 60)]) == [
        ("rejected", "device_clock_ahead")
    ]
    # A malformed event is refused on its own, with the field that is wrong. It
    # never blocks the good events sent with it (a tablet that sent one broken
    # event used to get 422 for the whole batch, forever, and stopped syncing).
    for bad in (
        _ev(oid, "kot", {"kot_no": "C1-1", "lines": [{**_line(cat), "qty": 0}]}),
        _ev(oid, "cancel", {"line_id": str(uuid.uuid4()), "qty": 1}),  # no reason
        _ev(oid, "move", {"table_id": None, "extra": 1}),
        {**_ev(oid, "move", {"table_id": None}), "kind": "teleport"},
    ):
        good = _ev(oid, "details", {"covers": 2})
        got = _sync(client, h, device.device_id, [bad, good])
        assert got[0][0] == "rejected" and got[0][1].startswith("invalid_event"), (bad, got)
        assert got[1] == ("accepted", None)
    # An envelope that is not a list of events at all is still a 422.
    r = client.post(
        f"{API}/sync/orders",
        json={"device_id": device.device_id, "events": [{"no": "id"}]},
        headers=h,
    )
    assert r.status_code == 422


def test_another_shops_table_is_dropped_from_the_order(client, shop_a, shop_b, setup):
    _, device, _, _ = setup
    build_catalogue(client, shop_b)
    hall_b = client.post(f"{API}/areas", json={"name": "Hall"}, headers=shop_b.owner_h).json()
    tb = client.post(
        f"{API}/tables", json={"area_id": hall_b["id"], "name": "B1"}, headers=shop_b.owner_h
    ).json()
    oid = str(uuid.uuid4())
    _sync(
        client,
        shop_a.cashier_h,
        device.device_id,
        [_ev(oid, "open", {"order_type": "dine_in", "table_id": tb["id"]})],
    )
    assert _live(client, shop_a.cashier_h)[oid]["table_id"] is None
    assert _live(client, shop_b.owner_h) == {}  # and shop B sees nothing of it


def test_only_the_owner_sets_up_tables(client, shop_a, setup):
    _, _, t1, _ = setup
    assert (
        client.post(f"{API}/areas", json={"name": "Roof"}, headers=shop_a.cashier_h).status_code
        == 403
    )
    assert (
        client.patch(
            f"{API}/tables/{t1['id']}", json={"seats": 9}, headers=shop_a.cashier_h
        ).status_code
        == 403
    )
    dup = client.post(
        f"{API}/tables", json={"area_id": t1["area_id"], "name": "T1"}, headers=shop_a.owner_h
    )
    assert dup.status_code == 409
    off = client.patch(
        f"{API}/tables/{t1['id']}", json={"is_active": False}, headers=shop_a.owner_h
    ).json()
    assert off["is_active"] is False


def test_order_history_is_for_the_owner_and_cannot_be_rewritten(client, shop_a, setup):
    from app.db.session import SessionLocal
    from app.db.tenancy import mark_system

    cat, device, t1, _ = setup
    oid = str(uuid.uuid4())
    l1 = _line(cat, 3)
    _sync(
        client,
        shop_a.cashier_h,
        device.device_id,
        [
            _ev(oid, "open", {"order_type": "dine_in", "table_id": t1["id"]}, -10),
            _ev(oid, "kot", {"kot_no": "C1-1", "lines": [l1]}, -9),
            _ev(oid, "cancel", {"line_id": l1["line_id"], "qty": 1, "reason": "wrong item"}, -8),
        ],
    )
    assert client.get(f"{API}/orders/{oid}", headers=shop_a.cashier_h).status_code == 403
    full = client.get(f"{API}/orders/{oid}", headers=shop_a.owner_h).json()
    assert [e["kind"] for e in full["events"]] == ["open", "kot", "cancel"]
    assert full["events"][2]["by_name"] == "Shop A cashier"
    assert full["state"]["cancellations"][0]["reason"] == "wrong item"

    with mark_system(SessionLocal()) as s, pytest.raises(Exception, match="append-only"):
        s.execute(text("UPDATE order_events SET data = '{}'::jsonb"))
        s.commit()


def test_owner_sees_cancellations_and_bills_changed_after_printing(client, shop_a, shop_b, setup):
    from app.core.time import business_date

    cat, device, t1, t2 = setup
    h = shop_a.cashier_h
    oid, gone = str(uuid.uuid4()), str(uuid.uuid4())
    l1 = _line(cat, 3)
    # The events go back 30 minutes. Run just after midnight in the shop, they
    # would straddle two shop days (CI failed at 00:07 IST on 5 Oct), so move
    # them an hour back, all onto yesterday, and ask for that day's report.
    now = datetime.now(UTC)
    back = -60 if business_date(now - timedelta(minutes=31)) != business_date(now) else 0
    day = business_date(now + timedelta(minutes=back - 30))
    _sync(
        client,
        h,
        device.device_id,
        [
            _ev(oid, "open", {"order_type": "dine_in", "table_id": t1["id"]}, back - 30),
            _ev(oid, "kot", {"kot_no": "C1-1", "lines": [l1]}, back - 29),
            _ev(
                oid,
                "cancel",
                {"line_id": l1["line_id"], "qty": 1, "reason": "wrong item"},
                back - 28,
            ),
            _ev(oid, "bill_printed", {}, back - 20),
            # The leak pattern: the bill is shown, then an item disappears.
            _ev(
                oid,
                "cancel",
                {"line_id": l1["line_id"], "qty": 1, "reason": "not served"},
                back - 19,
            ),
            _ev(gone, "open", {"order_type": "takeaway", "customer_name": "Priya"}, back - 15),
            _ev(gone, "kot", {"kot_no": "C1-2", "lines": [_line(cat, 2)]}, back - 14),
            _ev(gone, "cancel_order", {"reason": "left without paying"}, back - 10),
        ],
    )
    report = f"{API}/reports/service?business_date={day}"
    assert client.get(report, headers=h).status_code == 403
    r = client.get(report, headers=shop_a.owner_h).json()

    assert r["orders"] == {"dine_in": 1, "takeaway": 1, "delivery": 0}
    assert [(c["label"], c["qty"], c["reason"], c["after_bill"]) for c in r["cancellations"]] == [
        ("T1", 1, "wrong item", False),
        ("T1", 1, "not served", True),
    ]
    assert r["cancellations"][0]["by_name"] == "Shop A cashier"
    assert r["cancelled_value_paise"] == 4000
    (changed,) = r["changed_after_bill"]
    assert changed["label"] == "T1" and changed["bill_prints"] == 1
    assert changed["removed"] == [{"name": "Masala tea", "qty": 1, "reason": "not served"}]
    (cancelled,) = r["cancelled_orders"]
    assert cancelled == {
        "order_id": gone,
        "label": "Takeaway: Priya",
        "reason": "left without paying",
        "value_paise": 4000,
        "by_name": "Shop A cashier",
    }
    # T1 was never settled: it is still open at the end of the day.
    assert [(o["label"], o["status"]) for o in r["still_open"]] == [("T1", "open")]
    # Another shop's owner sees none of it (the route is keyed by date, not id).
    other = client.get(report, headers=shop_b.owner_h).json()
    assert other["orders"] == {"dine_in": 0, "takeaway": 0, "delivery": 0}
    assert other["cancellations"] == other["still_open"] == []

    # The same signals reach the owner's daily email.
    from app.db.session import SessionLocal
    from app.db.tenancy import bind_tenant
    from app.services.reports import daily_figures

    with SessionLocal() as s:
        bind_tenant(s, shop_a.shop.id)
        lines = daily_figures(s, day)["service"]
    assert lines == [
        "1 bill(s) changed after printing: T1",
        "2 item(s) cancelled after sending to the kitchen, worth ₹40",
        "1 order(s) cancelled",
        "1 order(s) not settled: T1",
    ]


def test_a_kot_with_options_is_taken_as_the_catalogue_sends_them(client, shop_a, setup):
    """Options reach the tablet from the catalogue with `scale_factor` as a JSON
    number (1.0, 1.5). The tablet copies the option into the KOT exactly as it got
    it. Orders used to accept only text there, so every table or takeaway order
    with an option was refused (found on staging, tablet C2, 4 Oct 2026)."""
    cat, device, t1, _ = setup
    h = shop_a.owner_h
    large = client.post(
        f"{API}/modifiers",
        json={"name": "Large", "price_delta_paise": 1000, "scale_factor": "1.5"},
        headers=h,
    ).json()
    catalogue = client.get(f"{API}/catalogue", headers=shop_a.cashier_h).json()
    mods = {m["name"]: m for m in catalogue["modifiers"]}

    def snap(m):
        return {
            "modifier_id": m["id"],
            "name": m["name"],
            "price_delta_paise": m["price_delta_paise"],
            "scale_factor": m["scale_factor"],
            "lines": [
                {"ingredient_id": x["ingredient_id"], "qty_delta": x["qty_delta"]}
                for x in m["lines"]
            ],
        }

    oid = str(uuid.uuid4())
    line = {**_line(cat), "modifiers": [snap(mods["Less sugar"]), snap(mods[large["name"]])]}
    got = _sync(
        client,
        shop_a.cashier_h,
        device.device_id,
        [
            _ev(oid, "open", {"order_type": "dine_in", "table_id": t1["id"]}, -3),
            _ev(oid, "kot", {"kot_no": "C1-1", "lines": [line]}, -2),
        ],
    )
    assert got == [("accepted", None), ("accepted", None)]
    (kot,) = [o for o in _live(client, h)[oid]["events"] if o["kind"] == "kot"]
    scales = [m["scale_factor"] for m in kot["data"]["lines"][0]["modifiers"]]
    assert [Decimal(str(s)) for s in scales] == [Decimal(1), Decimal("1.5")]
    # Nonsense is still refused, on its own.
    bad = {**_line(cat), "modifiers": [{**snap(mods["Less sugar"]), "scale_factor": "lots"}]}
    assert _sync(
        client,
        shop_a.cashier_h,
        device.device_id,
        [_ev(oid, "kot", {"kot_no": "C1-2", "lines": [bad]})],
    )[0][1].startswith("invalid_event")

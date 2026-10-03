"""PHASE 3 GATE: variance matches a hand-worked sample day to the paise.

Everything below happens on one business day, through the public API, in the
order a shop would do it. The expected numbers are worked out by hand in the
comments, so anyone can check the arithmetic on paper.

Costs (set by today's stock-in, paise per base unit):
  Milk        1 crate (12,000 ml) for Rs 672   -> 5.6  p/ml
  Tea powder  1 pouch (250 g) for Rs 125       -> 50   p/g
  Sugar       1 bag (1,000 g) for Rs 45        -> 4.5  p/g
  Oranges     3,000 g loose for Rs 240         -> 8    p/g
  Decoction   one batch = 2,000 ml milk + 60 g tea + 150 g sugar, makes 2,200 ml
              = (2000 x 5.6 + 60 x 50 + 150 x 4.5) / 2200 = 14,875 / 2,200
              = 6.761 p/ml (to 3 decimals)

Movements:
  Opening counts  milk 6,000 ml (12 packets), tea 500 g (2 pouches),
                  sugar 1,000 g, oranges 5,000 g, decoction 0
  Stock-in        as above
  2 batches       milk -4,000, tea -120, sugar -300, decoction +4,400
  Sales           30 masala tea (5 with Less sugar): decoction -3,000.
                  Less sugar is -5 g on sugar the cup does not contain: floored
                  at 0, so no sugar comes back.
                  4 orange juice: 4 x 555.556 = 2,222.224 g oranges
  Wastage         1 orange juice spilled: 555.556 g oranges = Rs 44.44
                  500 ml milk spoiled = Rs 28.00              (total Rs 72.44)

Expected closing:
  Milk       6,000 + 12,000 - 4,000 - 500             = 13,500 ml
  Tea powder 500 + 250 - 120                          =    630 g
  Sugar      1,000 + 1,000 - 300                      =  1,700 g
  Oranges    5,000 + 3,000 - 2,222.224 - 555.556      =  5,222.220 g
  Decoction  4,400 - 3,000                            =  1,400 ml

Blind count by the cashier, then one recount where outside tolerance (3%, oranges 8%):
  Milk       26 packets = 13,000 -> -500 vs usage 4,000 (3% = 120): RECOUNT -> 13,000
  Tea powder 2 pouches + 130 g = 630 -> 0
  Sugar      1 bag + 690 = 1,690 -> -10 vs usage 300 (3% = 9): RECOUNT -> 1,692 (-8)
  Oranges    5,100 -> -122.220 vs usage 2,222.224 (8% = 177.78): fine
  Decoction  1,350 -> -50 vs usage 3,000 (3% = 90): fine

Variance in rupees (half-up to the paisa):
  Milk       -500 x 5.6       = -2,800 p
  Sugar      -8 x 4.5         =    -36 p
  Oranges    -122.220 x 8     =   -977.76 -> -978 p
  Decoction  -50 x 6.761      =   -338.05 -> -338 p
  Missing in total            =  4,152 p = Rs 41.52

Adherence = expected usage / actual usage:
  Milk 4000/4500 = 88.9%   Sugar 300/308 = 97.4%   Oranges 2222.224/2344.444 = 94.8%
  Decoction 3000/3050 = 98.4%   Tea powder 120/120 = 100.0%
"""

from decimal import Decimal as D

import pytest

from app.core.time import business_date, utcnow
from tests.conftest import FakeDevice, build_catalogue


@pytest.fixture
def day(client, shop_a):
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h

    def packs(ing):
        units = client.get(f"/api/v1/ingredients/{ing['id']}", headers=h).json()["pack_units"]
        return {u["name"]: u["id"] for u in units}

    def ok(r, code=201):
        assert r.status_code == code, r.text
        return r.json()

    milk, tea, sugar = packs(cat.milk), packs(cat.tea_powder), packs(cat.sugar)
    # Opening counts
    for ing, body in [
        (cat.milk, {"packs": [{"pack_unit_id": milk["packet"], "qty": "12"}]}),
        (cat.tea_powder, {"packs": [{"pack_unit_id": tea["pouch"], "qty": "2"}]}),
        (cat.sugar, {"packs": [{"pack_unit_id": sugar["bag"], "qty": "1"}]}),
        (cat.oranges, {"loose_qty": "5000"}),
        (cat.decoction, {}),
    ]:
        ok(
            client.post(
                "/api/v1/stock/opening", json={"ingredient_id": ing["id"], **body}, headers=h
            )
        )
    # Stock-in (sets the costs)
    for ing, body in [
        (cat.milk, {"packs": [{"pack_unit_id": milk["crate"], "qty": "1"}], "cost_paise": 67200}),
        (
            cat.tea_powder,
            {"packs": [{"pack_unit_id": tea["pouch"], "qty": "1"}], "cost_paise": 12500},
        ),
        (cat.sugar, {"packs": [{"pack_unit_id": sugar["bag"], "qty": "1"}], "cost_paise": 4500}),
        (cat.oranges, {"loose_qty": "3000", "cost_paise": 24000}),
    ]:
        ok(client.post("/api/v1/stock-in", json={"ingredient_id": ing["id"], **body}, headers=h))
    # Two decoction batches, logged by the cashier
    ok(
        client.post(
            "/api/v1/prep-batches",
            json={"ingredient_id": cat.decoction["id"], "batches": "2"},
            headers=shop_a.cashier_h,
        )
    )
    # Sales
    device = FakeDevice(client, shop_a)
    bills = [device.bill([("Masala tea", 5, ["Less sugar"])])]
    bills += [device.bill([("Masala tea", 5, [])]) for _ in range(5)]
    bills += [device.bill([("Orange juice", 2, [])]) for _ in range(2)]
    results = device.sync(bills).json()["results"]
    assert {r["status"] for r in results} == {"accepted"}
    # Wastage, by the cashier
    spilled = ok(
        client.post(
            "/api/v1/wastage",
            json={"menu_item_id": cat.juice["id"], "qty": "1", "reason": "spilled"},
            headers=shop_a.cashier_h,
        )
    )
    spoiled = ok(
        client.post(
            "/api/v1/wastage",
            json={"ingredient_id": cat.milk["id"], "qty": "500", "reason": "spoiled"},
            headers=shop_a.cashier_h,
        )
    )
    assert spilled["value_paise"] is None and spoiled["value_paise"] is None  # cashier: no Rs
    return cat, device, milk, tea, sugar


def _url(suffix):
    return f"/api/v1/day-counts/{business_date(utcnow()).isoformat()}/{suffix}"


def test_hand_worked_day_matches_to_the_paise(client, shop_a, day):
    cat, device, milk, tea, sugar = day
    cashier, owner = shop_a.cashier_h, shop_a.owner_h

    # ---- Blind count by the cashier ----
    first = client.post(
        _url("counts"),
        json={
            "lines": [
                {
                    "ingredient_id": cat.milk["id"],
                    "packs": [{"pack_unit_id": milk["packet"], "qty": "26"}],
                },
                {
                    "ingredient_id": cat.tea_powder["id"],
                    "packs": [{"pack_unit_id": tea["pouch"], "qty": "2"}],
                    "loose_qty": "130",
                },
                {
                    "ingredient_id": cat.sugar["id"],
                    "packs": [{"pack_unit_id": sugar["bag"], "qty": "1"}],
                    "loose_qty": "690",
                },
                {"ingredient_id": cat.oranges["id"], "loose_qty": "5100"},
                {"ingredient_id": cat.decoction["id"], "loose_qty": "1350"},
            ]
        },
        headers=cashier,
    ).json()
    assert first == {
        "status": "counting",
        "recount": sorted([cat.milk["id"], cat.sugar["id"]]),
    }  # which items, never why or by how much
    assert client.get(_url("report"), headers=cashier).status_code == 403

    second = client.post(
        _url("counts"),
        json={
            "lines": [
                {
                    "ingredient_id": cat.milk["id"],
                    "packs": [{"pack_unit_id": milk["packet"], "qty": "26"}],
                },
                {
                    "ingredient_id": cat.sugar["id"],
                    "packs": [{"pack_unit_id": sugar["bag"], "qty": "1"}],
                    "loose_qty": "692",
                },
            ]
        },
        headers=cashier,
    ).json()
    assert second == {"status": "submitted", "recount": []}

    # ---- The owner's report, line by line against the hand-worked numbers ----
    rep = client.get(_url("report"), headers=owner).json()
    lines = {ln["name"]: ln for ln in rep["lines"]}
    expect = {
        # opening, stock-in, prep in, prep out, sold, wasted, expected, counted, variance,
        # variance in paise, adherence %
        "Milk": ("6000", "12000", "0", "4000", "0", "500", "13500", "13000", "-500", -2800, "88.9"),
        "Tea powder": ("500", "250", "0", "120", "0", "0", "630", "630", "0", 0, "100.0"),
        "Sugar": ("1000", "1000", "0", "300", "0", "0", "1700", "1692", "-8", -36, "97.4"),
        "Oranges": (
            "5000",
            "3000",
            "0",
            "0",
            "2222.224",
            "555.556",
            "5222.220",
            "5100",
            "-122.220",
            -978,
            "94.8",
        ),
        "Tea decoction": ("0", "0", "4400", "0", "3000", "0", "1400", "1350", "-50", -338, "98.4"),
    }
    assert set(lines) == set(expect)
    for name, (op, sin, pin, pout, sold, wasted, exp, cnt, var, paise, adh) in expect.items():
        ln = lines[name]
        got = tuple(
            D(ln[k])
            for k in (
                "opening",
                "stock_in",
                "prep_in",
                "prep_out",
                "sold",
                "wasted",
                "expected",
                "counted",
                "variance",
            )
        )
        assert got == tuple(D(x) for x in (op, sin, pin, pout, sold, wasted, exp, cnt, var)), name
        assert ln["variance_paise"] == paise, name
        assert D(ln["adherence_pct"]) == D(adh), name
    assert lines["Milk"]["flagged"] is True and lines["Milk"]["recounted"] is True
    assert lines["Sugar"]["flagged"] is False and lines["Sugar"]["recounted"] is True
    assert rep["missing_paise"] == 4152 and rep["surplus_paise"] == 0
    assert rep["flagged_count"] == 1
    assert rep["wastage_by_reason"] == {"spilled": 4444, "spoiled": 2800}
    assert rep["wastage_paise"] == 7244

    # ---- Approve: counted stock becomes the truth, the day locks ----
    approved = client.post(_url("approve"), headers=owner).json()
    assert approved["status"] == "approved"
    assert [ln["variance_paise"] for ln in approved["lines"]] == [-2800, -978, -36, -338, 0]
    stock = {r["name"]: D(r["on_hand"]) for r in client.get("/api/v1/stock", headers=owner).json()}
    assert stock == {
        "Milk": D("13000"),
        "Oranges": D("5100"),
        "Sugar": D("1692"),
        "Tea decoction": D("1350"),
        "Tea powder": D("630"),
    }
    assert client.post(_url("approve"), headers=owner).status_code == 409
    locked = client.post(
        _url("counts"),
        json={"lines": [{"ingredient_id": cat.milk["id"], "loose_qty": "1"}]},
        headers=cashier,
    )
    assert locked.status_code == 409

    # ---- A late bill from the closed day: stock stays equal to the count ----
    r = device.sync([device.bill([("Masala tea", 1, [])])]).json()["results"][0]
    assert r["status"] == "accepted"
    stock = {r["name"]: D(r["on_hand"]) for r in client.get("/api/v1/stock", headers=owner).json()}
    assert stock["Tea decoction"] == D("1350")  # the 100 ml was already gone at the count
    after = client.get(_url("report"), headers=owner).json()
    assert after["late_bills"] == 1
    assert after["late_bills_explained_paise"] == 676  # 100 ml x 6.761 p
    # The closed day's numbers never shift.
    assert {ln["name"]: ln["variance_paise"] for ln in after["lines"]}["Tea decoction"] == -338
    assert D({ln["name"]: ln for ln in after["lines"]}["Tea decoction"]["sold"]) == D("3000")


def test_owner_only_wastage_reasons(client, shop_a, day):
    cat = day[0]
    for reason in ("complimentary", "theft"):
        r = client.post(
            "/api/v1/wastage",
            json={"menu_item_id": cat.tea["id"], "qty": "1", "reason": reason},
            headers=shop_a.cashier_h,
        )
        assert r.status_code == 403, reason
    r = client.post(
        "/api/v1/wastage",
        json={"menu_item_id": cat.tea["id"], "qty": "1", "reason": "complimentary"},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 201 and r.json()["value_paise"] == 676  # 100 ml decoction


def test_wastage_needs_one_target_and_whole_servings(client, shop_a, day):
    cat = day[0]
    h = shop_a.cashier_h
    both = {
        "ingredient_id": cat.milk["id"],
        "menu_item_id": cat.tea["id"],
        "qty": "1",
        "reason": "spilled",
    }
    assert client.post("/api/v1/wastage", json=both, headers=h).status_code == 422
    half = {"menu_item_id": cat.tea["id"], "qty": "0.5", "reason": "spilled"}
    assert "whole servings" in client.post("/api/v1/wastage", json=half, headers=h).text


def test_count_sheet_is_blind(client, shop_a, day):
    sheet = client.get(_url("sheet"), headers=shop_a.cashier_h).json()
    assert sheet["status"] == "counting"
    keys = set(sheet["items"][0])
    assert not keys & {"expected", "on_hand", "expected_qty", "variance"}
    assert {"pack_units", "counted", "recount"} <= keys


def test_cannot_approve_before_the_count_is_finished(client, shop_a, day):
    assert client.post(_url("approve"), headers=shop_a.owner_h).status_code == 422
    assert client.post(_url("approve"), headers=shop_a.cashier_h).status_code == 403


def test_reads_do_not_create_the_day(client, shop_a, day):
    """The day-end screen loads the sheet and the report at the same moment;
    if reads inserted the day's row, the second one would fail."""
    assert client.get(_url("sheet"), headers=shop_a.cashier_h).status_code == 200
    assert client.get(_url("report"), headers=shop_a.owner_h).json()["lines"] == []
    from sqlalchemy import func, select

    from app.db.session import SessionLocal
    from app.db.tenancy import mark_system
    from app.models import DayCount

    with SessionLocal() as s:
        mark_system(s)
        assert s.scalar(select(func.count()).select_from(DayCount)) == 0


def test_simultaneous_requests_never_fail(client, shop_a, day):
    """Two tablets: sheet + report loading together, and two counts submitted
    at the same instant. Nobody gets a server error."""
    import threading

    cat = day[0]
    barrier = threading.Barrier(6)
    codes = []

    def call(method, url, h, body=None):
        barrier.wait()
        codes.append(client.request(method, url, json=body, headers=h).status_code)

    body = {"lines": [{"ingredient_id": cat.tea_powder["id"], "loose_qty": "630"}]}
    jobs = [
        ("GET", _url("sheet"), shop_a.cashier_h, None),
        ("GET", _url("sheet"), shop_a.owner_h, None),
        ("GET", _url("report"), shop_a.owner_h, None),
        ("GET", _url("report"), shop_a.owner_h, None),
        ("POST", _url("counts"), shop_a.cashier_h, body),
        ("POST", _url("counts"), shop_a.owner_h, body),
    ]
    threads = [threading.Thread(target=call, args=j) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200] * 6


def test_an_approved_day_counts_as_the_starting_point(client, shop_a):
    """No opening count, but yesterday-style close: today is no longer flagged."""
    cat = build_catalogue(client, shop_a)
    h = shop_a.owner_h
    stock = {r["name"]: r for r in client.get("/api/v1/stock", headers=h).json()}
    assert stock["Sugar"]["has_opening"] is False
    r = client.post(
        _url("counts"),
        json={"lines": [{"ingredient_id": cat.sugar["id"], "loose_qty": "0"}]},
        headers=h,
    )
    assert r.json()["status"] == "submitted"
    assert client.post(_url("approve"), headers=h).status_code == 200
    stock = {r["name"]: r for r in client.get("/api/v1/stock", headers=h).json()}
    assert stock["Sugar"]["has_opening"] is True
    assert stock["Milk"]["has_opening"] is False  # not counted
    # The closed day's own report still says it had no starting count before it.
    rep = client.get(_url("report"), headers=h).json()
    assert rep["lines"][0]["has_opening"] is False

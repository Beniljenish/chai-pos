"""Phase 10: the v1 gaps that make variance trustworthy.

10.1 SOP adherence trend. Built on the Phase 3 gate's hand-worked day, so the
numbers can be checked on paper (see test_phase3_gate.py for the day itself):

  Adherence = expected usage / actual usage
    Milk 4000/4500 = 88.9%   Sugar 300/308 = 97.4%   Oranges 2222.224/2344.444 = 94.8%
    Decoction 3000/3050 = 98.4%   Tea powder 120/120 = 100.0%

  Overall, weighted by value at the day's frozen cost (paise, half-up per line):
    expected  milk 4000 x 5.6 = 22,400   sugar 300 x 4.5 = 1,350
              oranges 2222.224 x 8 = 17,778   decoction 3000 x 6.761 = 20,283
              tea 120 x 50 = 6,000                              total 67,811
    actual    milk 4500 x 5.6 = 25,200   sugar 308 x 4.5 = 1,386
              oranges 2344.444 x 8 = 18,756   decoction 3050 x 6.761 = 20,621
              tea 6,000                                         total 71,963
    67,811 / 71,963 = 94.2%
"""

from datetime import date
from decimal import Decimal as D

from app.core.time import business_date, utcnow
from tests.test_phase3_gate import _url, day  # noqa: F401  (the hand-worked day)


def close_day(client, shop, cat, milk, tea, sugar):
    """The Phase 3 gate's count, recount and approval, without the checks."""
    lines = [
        {"ingredient_id": cat.milk["id"], "packs": [{"pack_unit_id": milk["packet"], "qty": "26"}]},
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
    client.post(_url("counts"), json={"lines": lines}, headers=shop.cashier_h)
    recount = [lines[0], {**lines[2], "loose_qty": "692"}]
    r = client.post(_url("counts"), json={"lines": recount}, headers=shop.cashier_h)
    assert r.json()["status"] == "submitted", r.text
    r = client.post(_url("approve"), headers=shop.owner_h)
    assert r.status_code == 200, r.text


TREND = "/api/v1/reports/adherence"


def test_trend_matches_the_hand_worked_day(client, shop_a, day):  # noqa: F811
    cat, device, milk, tea, sugar = day
    # Before the day is closed there is nothing to trend: an open count can change.
    empty = client.get(TREND, headers=shop_a.owner_h).json()
    assert empty["closed_days"] == [] and empty["lines"] == [] and empty["overall_pct"] is None

    close_day(client, shop_a, cat, milk, tea, sugar)
    today = business_date(utcnow()).isoformat()
    rep = client.get(TREND, headers=shop_a.owner_h).json()
    assert rep["closed_days"] == [today]
    assert D(rep["overall_pct"]) == D("94.2")
    got = {ln["name"]: ln for ln in rep["lines"]}
    expect = {
        # adherence, expected usage, actual usage, variance paise
        "Milk": ("88.9", "4000", "4500", -2800),
        "Oranges": ("94.8", "2222.224", "2344.444", -978),
        "Tea decoction": ("98.4", "3000", "3050", -338),
        "Sugar": ("97.4", "300", "308", -36),
        "Tea powder": ("100.0", "120", "120", 0),
    }
    assert set(got) == set(expect)
    for name, (pct, exp_use, act_use, paise) in expect.items():
        ln = got[name]
        assert D(ln["adherence_pct"]) == D(pct), name
        assert D(ln["expected_usage"]) == D(exp_use), name
        assert D(ln["actual_usage"]) == D(act_use), name
        assert ln["variance_paise"] == paise, name
        assert [(p["business_date"], D(p["adherence_pct"])) for p in ln["points"]] == [
            (today, D(pct))
        ]
    # Biggest loss in rupees first, so the owner reads the worst line first.
    assert [ln["name"] for ln in rep["lines"]][:2] == ["Milk", "Oranges"]


def test_a_late_bill_after_the_close_does_not_move_the_trend(client, shop_a, day):  # noqa: F811
    cat, device, milk, tea, sugar = day
    close_day(client, shop_a, cat, milk, tea, sugar)
    before = client.get(TREND, headers=shop_a.owner_h).json()
    late = device.bill([("Masala tea", 3, [])])
    assert device.sync([late]).json()["results"][0]["status"] == "accepted"
    assert client.get(TREND, headers=shop_a.owner_h).json() == before


def test_trend_is_owner_only_and_per_shop(client, shop_a, shop_b, day):  # noqa: F811
    cat, device, milk, tea, sugar = day
    close_day(client, shop_a, cat, milk, tea, sugar)
    assert client.get(TREND, headers=shop_a.cashier_h).status_code == 403
    other = client.get(TREND, headers=shop_b.owner_h).json()
    assert other["closed_days"] == [] and other["lines"] == []


def test_trend_window_is_bounded(client, shop_a):
    assert client.get(f"{TREND}?days=3", headers=shop_a.owner_h).status_code == 422
    assert client.get(f"{TREND}?days=93", headers=shop_a.owner_h).status_code == 422
    r = client.get(f"{TREND}?days=7", headers=shop_a.owner_h).json()
    assert (business_date(utcnow()) - date.fromisoformat(r["start"])).days == 6

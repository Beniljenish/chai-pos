# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Round three (README, "9.18"): busy pause, your usual, what you wasted."""

import uuid
from datetime import timedelta
from decimal import Decimal

from app.core.time import business_date, utcnow
from app.models import WastageEntry, WastageReason, WastageStatus
from app.services import online
from tests.conftest import build_catalogue
from tests.test_food_court import API, _live, _menu, _order, court  # noqa: F401


def _tea(client, c, which="a"):
    return _menu(client, c, which)["Masala tea"]["id"]


def _patch(client, shop, **body):
    r = client.patch(f"{API}/food-court/me", json=body, headers=shop.owner_h)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- busy pause
def test_busy_pause_is_off_until_the_owner_switches_it_on(client, shop_a, court):
    for _ in range(3):
        assert _order(client, court, [(_tea(client, court), 1)]).status_code == 201
    assert _menu(client, court)  # still orderable
    got = client.get(f"{API}/food-court", headers=shop_a.owner_h).json()
    assert got["busy_pause_on"] is False and got["paused_until"] is None


def test_it_pauses_by_itself_and_says_until_when(client, shop_a, court):
    _patch(client, shop_a, busy_pause_on=True, busy_limit=2)
    tea = _tea(client, court)
    assert _order(client, court, [(tea, 1)]).status_code == 201
    assert _order(client, court, [(tea, 1)]).status_code == 201
    third = _order(client, court, [(tea, 1)])
    assert third.status_code == 429 and third.json()["detail"]["code"] == "outlet_paused"
    until = third.json()["detail"]["until"]
    menu = client.get(f"{API}/public/courts/{court['slug']}/outlets/{court['a']}/menu").json()
    assert menu["paused_until"] == until
    assert client.get(f"{API}/food-court", headers=shop_a.owner_h).json()["paused_until"]
    # the other outlet is not affected
    assert _order(client, court, [(_tea(client, court, "b"), 1)], which="b").status_code == 201


def test_the_owner_can_open_again_and_switching_off_lifts_a_pause(client, shop_a, court):
    _patch(client, shop_a, busy_pause_on=True, busy_limit=2)
    tea = _tea(client, court)
    for _ in range(2):
        _order(client, court, [(tea, 1)]).raise_for_status()
    assert _order(client, court, [(tea, 1)]).status_code == 429
    # raising the limit does not lift a running pause; "open now" does
    _patch(client, shop_a, busy_limit=20)
    assert _order(client, court, [(tea, 1)]).status_code == 429
    assert _patch(client, shop_a, resume_now=True)["paused_until"] is None
    assert _order(client, court, [(tea, 1)]).status_code == 201
    # switching the feature off lifts a pause too
    _patch(client, shop_a, busy_limit=2)
    assert _order(client, court, [(tea, 1)]).status_code == 429
    _patch(client, shop_a, busy_pause_on=False)
    assert _order(client, court, [(tea, 1)]).status_code == 201


def test_a_pause_ends_by_itself(client, shop_a, court):
    from sqlalchemy import select

    from app.models import FoodCourtOutlet

    _patch(client, shop_a, busy_pause_on=True, busy_limit=2)
    tea = _tea(client, court)
    for _ in range(2):
        _order(client, court, [(tea, 1)]).raise_for_status()
    assert _order(client, court, [(tea, 1)]).status_code == 429
    with online.system_session() as db:
        o = db.scalar(select(FoodCourtOutlet).where(FoodCourtOutlet.shop_id == shop_a.shop.id))
        o.paused_until = utcnow() - timedelta(minutes=1)
        o.busy_limit = 40
        db.commit()
    assert _order(client, court, [(tea, 1)]).status_code == 201


# ---------------------------------------------------------------- your usual
def _usual(client, c, who=None, which="a"):
    r = client.get(
        f"{API}/customer/usual", params={"outlet_id": c[which]}, headers=who or c["customer"]
    )
    assert r.status_code == 200, r.text
    return r.json()["usual"]


def test_your_usual_needs_two_orders_and_shows_what_repeats(client, shop_a, court):
    tea, juice = _tea(client, court), _menu(client, court)["Orange juice"]["id"]
    assert _usual(client, court) == []
    _order(client, court, [(tea, 2), (juice, 1)]).raise_for_status()
    assert _usual(client, court) == []  # one order is not a habit
    _order(client, court, [(tea, 2)]).raise_for_status()
    _order(client, court, [(tea, 1)]).raise_for_status()
    got = _usual(client, court)
    assert [(u["name"], u["qty"]) for u in got] == [("Masala tea", 2)]  # juice was once: left out
    assert got[0]["menu_item_id"] == tea
    # another outlet's orders do not count here, and nothing is shown to someone else
    assert _usual(client, court, which="b") == []
    assert client.get(f"{API}/customer/usual", params={"outlet_id": court["a"]}).status_code == 401


# ---------------------------------------------------------------- what you wasted
def test_the_wasted_report_adds_up_what_counts(client, shop_a):
    cat = build_catalogue(client, shop_a)
    today = business_date(utcnow())
    monday = today - timedelta(days=today.weekday())
    if monday == today:
        monday -= timedelta(days=7)

    def waste(ingredient, paise, day, reason, status=WastageStatus.approved):
        db.add(
            WastageEntry(
                ingredient_id=uuid.UUID(ingredient),
                qty=Decimal(1),
                reason=reason,
                value_paise=paise,
                business_date=day,
                created_by=shop_a.owner.id,
                created_at=utcnow(),
                status=status,
            )
        )

    with online.shop_session(shop_a.shop.id) as db:
        waste(cat.milk["id"], 60000, monday, WastageReason.spoiled)
        waste(cat.milk["id"], 32000, monday - timedelta(days=7), WastageReason.spoiled)
        waste(cat.oranges["id"], 61000, today - timedelta(days=1), WastageReason.spilled)
        waste(
            cat.oranges["id"], 99999, today, WastageReason.spoiled, WastageStatus.pending
        )  # not yet
        waste(
            cat.oranges["id"], 77777, today, WastageReason.spoiled, WastageStatus.rejected
        )  # reversed
        waste(cat.milk["id"], 5000, today - timedelta(days=60), WastageReason.spoiled)  # too old
        db.commit()
    r = client.get(f"{API}/reports/wasted", headers=shop_a.owner_h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["total_paise"] == 60000 + 32000 + 61000 and got["entries"] == 3
    assert got["items"][0] == {"name": "Milk", "paise": 92000}
    assert got["worst_day"]["weekday"] == "Monday" and got["worst_day"]["top_reason"] == "spoiled"
    assert client.get(f"{API}/reports/wasted", headers=shop_a.cashier_h).status_code == 403

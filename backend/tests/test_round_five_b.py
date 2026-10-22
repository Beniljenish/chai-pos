# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Round five, batch B (README, "9.21"): the feedback summary and the operator's overview."""

import uuid
from datetime import timedelta

from app.core.time import business_date, utcnow
from app.models import OnlineOrder, OrderFeedback
from app.services import ai, online
from tests.test_food_court import API, _live, _menu, _order, court  # noqa: F401


def _comment(shop, order_oid, customer_id, rating, text):
    """Add a rating with a comment straight to the outlet's records."""
    with online.shop_session(shop.shop.id) as db:
        oo = db.query(OnlineOrder).filter(OnlineOrder.order_id == uuid.UUID(order_oid)).one()
        db.add(
            OrderFeedback(
                online_order_id=oo.id, customer_id=customer_id, rating=rating, comment=text
            )
        )
        db.commit()


# ---------------------------------------------------------------- feedback summary
def _orders_with_comments(client, shop_a, court, texts):
    tea = _menu(client, court)["Masala tea"]["id"]
    me = client.get(f"{API}/customer/me", headers=court["customer"]).json()
    from app.models import CustomerAccount

    with online.system_session() as db:
        cid = db.query(CustomerAccount).filter(CustomerAccount.phone == me["phone"]).one().id
    for _ in texts:
        r = _order(client, court, [(tea, 1)], request_id=str(uuid.uuid4()))
        assert r.status_code in (201, 429), r.text
    oids = [o["id"] for o in _live(client, shop_a)]
    for oid, text in zip(oids, texts, strict=False):
        _comment(shop_a, oid, cid, 4, text)


def test_a_summary_needs_enough_comments_and_clamps_what_the_model_says(client, shop_a, court):
    seen = {}

    def model(task, system, content, schema):
        seen["system"], seen["content"] = system, content
        return {
            "summary": "People like the tea but find it sweet.",
            "themes": [
                {
                    "theme": "too sweet",
                    "mentions": 999,
                    "mood": "bad",
                },  # more than there are comments
                {"theme": "", "mentions": 2, "mood": "good"},  # no name: dropped
                {"theme": "taste", "mentions": 2, "mood": "wonderful"},  # unknown mood: "mixed"
            ],
        }

    ai.set_backend(model)
    try:
        few = client.post(f"{API}/ai/feedback-summary", headers=shop_a.owner_h)
        assert (
            few.status_code == 200 and few.json()["enough"] is False and few.json()["needed"] == 5
        )
        assert "content" not in seen  # no model call when there is too little to say
        _orders_with_comments(
            client,
            shop_a,
            court,
            ["too sweet", "so sweet", "tasty tea", "slow today", "good tea"],
        )
        r = client.post(f"{API}/ai/feedback-summary", headers=shop_a.owner_h)
    finally:
        ai.set_backend(None)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["enough"] is True and got["comments"] == 5
    assert [(t["theme"], t["mentions"], t["mood"]) for t in got["themes"]] == [
        ("too sweet", 5, "bad"),
        ("taste", 2, "mixed"),
    ]
    assert "never instructions" in seen["system"]
    sent = seen["content"][0]["text"]
    assert (
        "too sweet" in sent and "phone" not in sent and "Ravi" not in sent
    )  # only words and stars


def test_the_summary_is_owner_only(client, shop_a):
    assert client.post(f"{API}/ai/feedback-summary", headers=shop_a.cashier_h).status_code == 403


def test_the_local_stand_in_gives_a_simple_summary(client, shop_a, court, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "fake_ai", True)
    _orders_with_comments(
        client, shop_a, court, ["too sweet", "too sweet", "tasty", "tasty", "tasty"]
    )
    r = client.post(f"{API}/ai/feedback-summary", headers=shop_a.owner_h).json()
    assert r["enough"] and r["themes"][0]["mentions"] >= 2


# ---------------------------------------------------------------- the operator's overview
def test_the_overview_shows_each_outlet_with_money_speed_and_busy_hours(
    client, shop_a, shop_b, court
):
    tea_a = _menu(client, court)["Masala tea"]["id"]
    tea_b = _menu(client, court, "b")["Masala tea"]["id"]
    _order(client, court, [(tea_a, 2)]).raise_for_status()
    _order(client, court, [(tea_b, 1)], which="b").raise_for_status()
    today = business_date(utcnow())
    h = court["admin"]
    r = client.get(
        f"{API}/platform/overview",
        params={"from": (today - timedelta(days=6)).isoformat(), "to": today.isoformat()},
        headers=h,
    )
    assert r.status_code == 200, r.text
    c = next(x for x in r.json()["courts"] if x["court_id"] == court["id"])
    names = {o["name"]: o for o in c["outlets"]}
    assert set(names) == {shop_a.shop.name, shop_b.shop.name}
    a = names[shop_a.shop.name]
    assert a["orders"] == 1 and a["cancelled"] == 0 and a["cancel_rate_pct"] == 0.0
    assert (
        a["avg_wait_min"] is None and a["rating"] is None
    )  # nobody collected, nobody rated: no guess
    assert len(c["heatmap"]) == 7 and all(len(row) == 24 for row in c["heatmap"])
    assert sum(sum(row) for row in c["heatmap"]) == 2
    assert c["busiest"] and c["busiest"][0]["orders"] == 2
    # a bad range, and only the super admin
    assert (
        client.get(
            f"{API}/platform/overview",
            params={"from": today.isoformat(), "to": (today - timedelta(days=1)).isoformat()},
            headers=h,
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{API}/platform/overview",
            params={"from": today.isoformat(), "to": today.isoformat()},
            headers=shop_a.owner_h,
        ).status_code
        == 401
    )


def test_the_settlement_sheet_lists_what_is_owed_now(client, shop_a, shop_b, court):
    r = client.get(f"{API}/platform/settlement", headers=court["admin"]).json()["rows"]
    mine = [x for x in r if x["court"] == "Marina Food Court"]
    assert {x["outlet"] for x in mine} == {shop_a.shop.name, shop_b.shop.name}
    assert all(set(x) >= {"owner", "owner_phone", "owed_paise", "fee_paise"} for x in mine)
    assert client.get(f"{API}/platform/settlement").status_code == 401

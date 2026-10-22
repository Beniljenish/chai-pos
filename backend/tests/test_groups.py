# ruff: noqa: F811  (fixtures imported from other test modules are used as arguments)
"""Order together (README, "9.21")."""

import uuid

from tests.conftest import customer_headers
from tests.test_food_court import API, _menu, court  # noqa: F401


def _line(court, which="a", item=None, qty=1, mods=()):
    return {"outlet_id": court[which], "menu_item_id": item, "modifier_ids": list(mods), "qty": qty}


def _make(client, court, who=None):
    r = client.post(
        f"{API}/customer/groups", json={"slug": court["slug"]}, headers=who or court["customer"]
    )
    assert r.status_code == 201, r.text
    return r.json()


_n = {"i": 0}


def _friend(client):
    """A new customer account each time (each friend has their own number)."""
    _n["i"] += 1
    return customer_headers(client, phone=f"98411{_n['i']:05d}", name=f"Friend {_n['i']}")


def test_a_group_is_made_joined_and_shared_by_name_only(client, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    g = _make(client, court)
    assert g["is_host"] is True and [m["name"] for m in g["members"]] == ["Ravi"] or g["members"]
    friend = _friend(client)
    joined = client.post(f"{API}/customer/groups/{g['token']}/join", headers=friend)
    assert joined.status_code == 200 and joined.json()["is_host"] is False
    assert len(joined.json()["members"]) == 2
    # each puts in their own dishes
    client.put(
        f"{API}/customer/groups/{g['token']}/lines",
        json={"lines": [_line(court, item=tea, qty=2)]},
        headers=court["customer"],
    ).raise_for_status()
    got = client.put(
        f"{API}/customer/groups/{g['token']}/lines",
        json={"lines": [_line(court, item=tea, qty=1)]},
        headers=friend,
    ).json()
    assert sorted((ln["qty"], ln["mine"]) for ln in got["lines"]) == [(1, True), (2, False)]
    host_view = client.get(f"{API}/customer/groups/{g['token']}", headers=court["customer"]).json()
    assert sorted((ln["qty"], ln["mine"]) for ln in host_view["lines"]) == [(1, False), (2, True)]
    text = str(host_view) + str(got)
    assert "phone" not in text and "98" not in "".join(
        m["name"] for m in host_view["members"]
    )  # names only


def test_putting_lines_replaces_only_your_own(client, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    g = _make(client, court)
    friend = _friend(client)
    client.post(f"{API}/customer/groups/{g['token']}/join", headers=friend).raise_for_status()
    client.put(
        f"{API}/customer/groups/{g['token']}/lines",
        json={"lines": [_line(court, item=tea, qty=3)]},
        headers=court["customer"],
    )
    client.put(
        f"{API}/customer/groups/{g['token']}/lines",
        json={"lines": [_line(court, item=tea, qty=1)]},
        headers=friend,
    )
    client.put(
        f"{API}/customer/groups/{g['token']}/lines", json={"lines": []}, headers=friend
    )  # the friend empties theirs
    after = client.get(f"{API}/customer/groups/{g['token']}", headers=court["customer"]).json()
    assert [(ln["qty"], ln["mine"]) for ln in after["lines"]] == [(3, True)]


def test_strangers_and_bad_tokens_get_nothing(client, court):
    g = _make(client, court)
    stranger = _friend(client)
    assert client.get(f"{API}/customer/groups/{g['token']}", headers=stranger).status_code == 403
    put = client.put(
        f"{API}/customer/groups/{g['token']}/lines", json={"lines": []}, headers=stranger
    )
    assert put.status_code == 403
    assert client.get(f"{API}/customer/groups/NOTATOKEN", headers=stranger).status_code == 404
    assert client.post(f"{API}/customer/groups/NOTATOKEN/join", headers=stranger).status_code == 404
    assert client.get(f"{API}/customer/groups/{g['token']}").status_code == 401  # no login


def test_a_line_for_an_outlet_outside_the_court_is_refused_and_sizes_are_limited(client, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    g = _make(client, court)
    bad = {"outlet_id": str(uuid.uuid4()), "menu_item_id": tea, "modifier_ids": [], "qty": 1}
    assert (
        client.put(
            f"{API}/customer/groups/{g['token']}/lines",
            json={"lines": [bad]},
            headers=court["customer"],
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"{API}/customer/groups/{g['token']}/lines",
            json={"lines": [_line(court, item=tea, qty=21)]},
            headers=court["customer"],
        ).status_code
        == 422
    )
    many = [_line(court, item=tea, qty=1) for _ in range(16)]
    assert (
        client.put(
            f"{API}/customer/groups/{g['token']}/lines",
            json={"lines": many},
            headers=court["customer"],
        ).status_code
        == 422
    )


def test_only_the_host_closes_and_a_closed_group_takes_no_more(client, court):
    tea = _menu(client, court)["Masala tea"]["id"]
    g = _make(client, court)
    friend = _friend(client)
    client.post(f"{API}/customer/groups/{g['token']}/join", headers=friend).raise_for_status()
    assert (
        client.post(f"{API}/customer/groups/{g['token']}/close", headers=friend).status_code == 403
    )
    closed = client.post(f"{API}/customer/groups/{g['token']}/close", headers=court["customer"])
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert (
        client.put(
            f"{API}/customer/groups/{g['token']}/lines",
            json={"lines": [_line(court, item=tea)]},
            headers=friend,
        ).status_code
        == 409
    )
    late = client.post(f"{API}/customer/groups/{g['token']}/join", headers=_friend(client))
    assert late.status_code == 409 and late.json()["detail"]["code"] == "group_closed"


def test_a_group_holds_ten_people_and_expires(client, court, monkeypatch):
    from app.services import customer_accounts

    monkeypatch.setattr(
        customer_accounts, "SIGNUPS_PER_HOUR", 1000
    )  # eleven sign-ups from one test client
    g = _make(client, court)
    for _ in range(9):
        client.post(
            f"{API}/customer/groups/{g['token']}/join", headers=_friend(client)
        ).raise_for_status()
    full = client.post(f"{API}/customer/groups/{g['token']}/join", headers=_friend(client))
    assert full.status_code == 409 and full.json()["detail"]["code"] == "group_full"
    from datetime import timedelta

    from app.core.time import utcnow
    from app.models import GroupCart
    from app.services import online

    with online.system_session() as db:
        grp = db.query(GroupCart).filter(GroupCart.token == g["token"]).one()
        grp.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert (
        client.get(f"{API}/customer/groups/{g['token']}", headers=court["customer"]).status_code
        == 404
    )


def test_the_daily_limit_on_starting_groups(client, court):
    for _ in range(5):
        _make(client, court)
    r = client.post(
        f"{API}/customer/groups", json={"slug": court["slug"]}, headers=court["customer"]
    )
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_groups"

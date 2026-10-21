"""Customer accounts for food-court ordering (services/customer_accounts.py).

What matters: ordering needs an account, an account's token opens nothing else (and no
other token opens it), history shows only your own orders, and a reset or password change
ends every older session."""

import uuid

from tests.conftest import PASSWORD, build_catalogue, customer_headers, platform_headers
from tests.test_food_court import API, _live, _menu, _order, court  # noqa: F401


def _login(client, phone, password=PASSWORD):
    return client.post(f"{API}/customer/login", json={"phone": phone, "password": password})


def test_signing_up_gives_a_token_that_opens_the_account(client):
    r = client.post(
        f"{API}/customer/signup",
        json={"name": " Ravi ", "phone": "98400 12345", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text
    assert r.json()["account"] == {
        "name": "Ravi",
        "phone": "9840012345",
        "must_change_password": False,
    }
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"{API}/customer/me", headers=h).json()["phone"] == "9840012345"


def test_one_number_one_account_and_the_password_is_checked(client):
    body = {"name": "Ravi", "phone": "9840012345", "password": PASSWORD}
    assert client.post(f"{API}/customer/signup", json=body).status_code == 201
    again = client.post(f"{API}/customer/signup", json=body)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "phone_taken"
    for pw in ("short", "password1", "my9841100000pw"):
        r = client.post(
            f"{API}/customer/signup", json={**body, "phone": "9841100000", "password": pw}
        )
        assert r.status_code == 422 and r.json()["detail"]["code"] == "weak_password", pw


def test_wrong_phone_and_wrong_password_look_the_same_and_lock_after_five(client):
    customer_headers(client)
    unknown = _login(client, "9999999999")
    wrong = _login(client, "9840012345", "not-the-password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    for _ in range(4):  # five wrong passwords in all (one above)
        assert _login(client, "9840012345", "not-the-password").status_code == 401
    locked = _login(client, "9840012345")  # even the right password waits
    assert locked.status_code == 429


def test_ordering_needs_a_customer_account(client, shop_a, court):  # noqa: F811
    tea = _menu(client, court)["Masala tea"]["id"]
    url = f"{API}/public/courts/{court['slug']}/outlets/{court['a']}/orders"
    body = {"request_id": str(uuid.uuid4()), "items": [{"menu_item_id": tea, "qty": 1}]}
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers={"Authorization": "Bearer junk"}).status_code == 401
    # a shop owner's and the super admin's tokens are the wrong kind
    for h in (shop_a.owner_h, court["admin"]):
        assert client.post(url, json=body, headers=h).status_code == 401
    assert _live(client, shop_a) == []


def test_a_customer_token_opens_nothing_else(client, shop_a, court):  # noqa: F811
    h = court["customer"]
    for method, path in [
        ("get", "/users"),
        ("get", "/catalogue"),
        ("get", "/orders/live"),
        ("get", "/food-court"),
        ("get", "/platform/courts"),
        ("get", "/platform/me"),
        ("post", "/platform/customers/reset-password"),
    ]:
        assert getattr(client, method)(f"{API}{path}", headers=h).status_code in (401, 403, 422), (
            path
        )
    # and the other tokens do not open the customer's account
    for other in (shop_a.owner_h, court["admin"]):
        assert client.get(f"{API}/customer/me", headers=other).status_code == 401
        assert client.get(f"{API}/customer/orders", headers=other).status_code == 401


def test_the_order_carries_the_accounts_name_and_phone(client, shop_a, court):  # noqa: F811
    tea = _menu(client, court)["Masala tea"]["id"]
    token = _order(client, court, [(tea, 1)]).json()["token"]
    live = next(o for o in _live(client, shop_a) if o["state"]["customer_name"].startswith(token))
    assert live["state"]["customer_name"] == f"{token} Ravi"
    assert live["state"]["customer_phone"] == "9840012345"


def test_history_is_yours_only_and_spans_outlets(client, shop_a, shop_b, court):  # noqa: F811
    tea_a = _menu(client, court, "a")["Masala tea"]["id"]
    tea_b = _menu(client, court, "b")["Masala tea"]["id"]
    mine_a = _order(client, court, [(tea_a, 2)]).json()
    mine_b = _order(client, court, [(tea_b, 1)], which="b").json()
    other = customer_headers(client, "9841100000", "Priya")
    _order(client, court, [(tea_a, 1)], who=other)

    mine = client.get(f"{API}/customer/orders", headers=court["customer"]).json()["orders"]
    assert [o["token"] for o in mine] == [mine_b["token"], mine_a["token"]]  # newest first
    assert {o["outlet"] for o in mine} == {shop_a.shop.name, shop_b.shop.name}
    assert all(o["status"] == "received" and o["court"] == "Marina Food Court" for o in mine)
    assert mine[1]["items"] == [{"name": "Masala tea", "qty": 2}]
    # the status link in a history row works
    seen = client.get(f"{API}/public/orders/{mine[0]['status_key']}").json()
    assert seen["token"] == mine_b["token"]

    theirs = client.get(f"{API}/customer/orders", headers=other).json()["orders"]
    assert len(theirs) == 1 and theirs[0]["items"] == [{"name": "Masala tea", "qty": 1}]


def test_someone_elses_request_id_reveals_nothing(client, shop_a, court):  # noqa: F811
    tea = _menu(client, court)["Masala tea"]["id"]
    rid = str(uuid.uuid4())
    mine = _order(client, court, [(tea, 1)], request_id=rid)
    assert mine.status_code == 201
    other = customer_headers(client, "9841100000", "Priya")
    stolen = _order(client, court, [(tea, 1)], who=other, request_id=rid)
    assert stolen.status_code == 404
    assert "status_key" not in stolen.text


def test_changing_the_password_ends_other_sessions(client):
    old = customer_headers(client)
    bad = client.post(
        f"{API}/customer/password",
        json={"current_password": "wrong-one-123", "new_password": "a-better-pass-9"},
        headers=old,
    )
    assert bad.status_code == 403
    ok = client.post(
        f"{API}/customer/password",
        json={"current_password": PASSWORD, "new_password": "a-better-pass-9"},
        headers=old,
    )
    assert ok.status_code == 200, ok.text
    assert client.get(f"{API}/customer/me", headers=old).status_code == 401  # the old session
    new = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.get(f"{API}/customer/me", headers=new).status_code == 200
    assert _login(client, "9840012345").status_code == 401
    assert _login(client, "9840012345", "a-better-pass-9").status_code == 200


def test_the_super_admin_resets_a_forgotten_password(client):
    old = customer_headers(client)
    for _ in range(5):  # locked out: the usual reason someone asks
        _login(client, "9840012345", "not-the-password")
    assert _login(client, "9840012345").status_code == 429

    admin = platform_headers(client)
    r = client.post(
        f"{API}/platform/customers/reset-password", json={"phone": "98400 12345"}, headers=admin
    )
    assert r.status_code == 200, r.text
    temp = r.json()["temporary_password"]
    assert len(temp) == 8 and r.json()["name"] == "Ravi"

    assert client.get(f"{API}/customer/me", headers=old).status_code == 401
    assert _login(client, "9840012345").status_code == 401  # the forgotten one is gone
    got = _login(client, "9840012345", temp)
    assert got.status_code == 200 and got.json()["account"]["must_change_password"] is True
    h = {"Authorization": f"Bearer {got.json()['access_token']}"}
    done = client.post(
        f"{API}/customer/password",
        json={"current_password": temp, "new_password": "my-own-secret-7"},
        headers=h,
    )
    assert done.json()["account"]["must_change_password"] is False

    missing = client.post(
        f"{API}/platform/customers/reset-password", json={"phone": "9999999999"}, headers=admin
    )
    assert missing.status_code == 404


def test_only_the_super_admin_can_reset(client, shop_a):
    customer_headers(client)
    r = client.post(
        f"{API}/platform/customers/reset-password",
        json={"phone": "9840012345"},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 401
    assert (
        client.post(
            f"{API}/platform/customers/reset-password", json={"phone": "9840012345"}
        ).status_code
        == 401
    )


def test_a_switched_off_account_is_out_at_once(client):
    from app.db.session import SessionLocal
    from app.db.tenancy import mark_system
    from app.models import CustomerAccount

    h = customer_headers(client)
    with mark_system(SessionLocal()) as db:
        db.query(CustomerAccount).update({"is_active": False})
        db.commit()
    assert client.get(f"{API}/customer/me", headers=h).status_code == 401
    assert _login(client, "9840012345").status_code == 401


def test_rename_keeps_old_orders_as_placed(client, shop_a, court):  # noqa: F811
    tea = _menu(client, court)["Masala tea"]["id"]
    token = _order(client, court, [(tea, 1)]).json()["token"]
    r = client.patch(f"{API}/customer/me", json={"name": "Ravi Kumar"}, headers=court["customer"])
    assert r.json()["name"] == "Ravi Kumar"
    # the till shows the name the order was placed under
    names = [o["state"]["customer_name"] for o in _live(client, shop_a)]
    assert f"{token} Ravi" in names
    _ = build_catalogue  # keep the shared import used

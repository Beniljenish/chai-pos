"""Staff accounts: each person has their own login and password.

- The owner creates staff with a first password; the person must replace it
  before the server lets them do anything else (the owner knows the first one).
- Five wrong passwords lock the account for 15 minutes; the owner's reset clears it.
- A reset or a deactivation logs the person out everywhere.
- Bills are credited to who rang them up on the tablet, not who synced them.
"""

import pytest

from tests.conftest import FakeDevice, build_catalogue

API = "/api/v1"
FIRST = "ginger4821"  # an owner-chosen first password


def _login(client, phone, password):
    return client.post(f"{API}/auth/login", json={"phone": phone, "password": password})


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _new_staff(client, owner_h, phone="9876500001", name="Ravi", role="cashier"):
    r = client.post(
        f"{API}/users",
        json={"name": name, "phone": phone, "role": role, "password": FIRST},
        headers=owner_h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _change(client, token, current, new):
    return client.post(
        f"{API}/auth/password",
        json={"current_password": current, "new_password": new},
        headers=_h(token),
    )


def test_new_staff_must_set_their_own_password_first(client, shop_a):
    build_catalogue(client, shop_a)
    ravi = _new_staff(client, shop_a.owner_h)
    assert ravi["must_change_password"] is True

    tokens = _login(client, "9876500001", FIRST).json()
    access = tokens["access_token"]
    # Logged in, but nothing works until the password is theirs...
    r = client.get(f"{API}/catalogue", headers=_h(access))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "password_change_required"
    # ...except finding out who they are, and changing it.
    me = client.get(f"{API}/auth/me", headers=_h(access)).json()
    assert me["must_change_password"] is True

    assert _change(client, access, "wrong-one", "masala-tea-77").status_code == 422
    assert "too easy" in _change(client, access, FIRST, "12345678").json()["detail"]
    assert "phone" in _change(client, access, FIRST, "x9876500001").json()["detail"]
    assert "different" in _change(client, access, FIRST, FIRST).json()["detail"]

    r = _change(client, access, FIRST, "masala-tea-77")
    assert r.status_code == 200, r.text
    fresh = r.json()
    assert client.get(f"{API}/catalogue", headers=_h(fresh["access_token"])).status_code == 200
    assert (
        client.get(f"{API}/auth/me", headers=_h(fresh["access_token"])).json()[
            "must_change_password"
        ]
        is False
    )
    # The login made with the owner's password is over everywhere.
    old = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert old.status_code == 401
    # The first password no longer works; the new one does.
    assert _login(client, "9876500001", FIRST).status_code == 401
    assert _login(client, "9876500001", "masala-tea-77").status_code == 200


def test_owner_cannot_give_an_easy_first_password(client, shop_a):
    r = client.post(
        f"{API}/users",
        json={"name": "X", "phone": "9876500002", "password": "password"},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 422


def test_five_wrong_passwords_lock_the_account_until_the_owner_resets_it(client, shop_a):
    ravi = _new_staff(client, shop_a.owner_h)
    for _ in range(5):
        assert _login(client, "9876500001", "not-it-123").status_code == 401
    # Locked: even the right password is refused, with a plain explanation.
    r = _login(client, "9876500001", FIRST)
    assert r.status_code == 429 and "15 minutes" in r.json()["detail"]
    users = {u["phone"]: u for u in client.get(f"{API}/users", headers=shop_a.owner_h).json()}
    assert users["9876500001"]["locked"] is True

    r = client.patch(
        f"{API}/users/{ravi['id']}", json={"password": "lemon-5512"}, headers=shop_a.owner_h
    )
    assert r.status_code == 200 and r.json()["locked"] is False
    assert _login(client, "9876500001", "lemon-5512").status_code == 200


def test_a_right_password_resets_the_wrong_count(client, shop_a):
    _new_staff(client, shop_a.owner_h)
    for _ in range(4):
        _login(client, "9876500001", "not-it-123")
    assert _login(client, "9876500001", FIRST).status_code == 200
    for _ in range(4):
        _login(client, "9876500001", "not-it-123")
    assert _login(client, "9876500001", FIRST).status_code == 200  # still not locked


def test_reset_and_deactivate_log_the_person_out(client, shop_a):
    ravi = _new_staff(client, shop_a.owner_h)
    t = _login(client, "9876500001", FIRST).json()
    t = _change(client, t["access_token"], FIRST, "masala-tea-77").json()

    r = client.patch(
        f"{API}/users/{ravi['id']}", json={"password": "lemon-5512"}, headers=shop_a.owner_h
    )
    assert r.json()["must_change_password"] is True
    assert (
        client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code
        == 401
    )

    t = _login(client, "9876500001", "lemon-5512").json()
    client.patch(
        f"{API}/users/{ravi['id']}", json={"is_active": False}, headers=shop_a.owner_h
    ).raise_for_status()
    assert (
        client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code
        == 401
    )
    assert client.get(f"{API}/auth/me", headers=_h(t["access_token"])).status_code == 401
    assert _login(client, "9876500001", "lemon-5512").status_code == 401


def test_owner_changes_own_password_only_with_the_current_one(client, shop_a):
    r = client.patch(
        f"{API}/users/{shop_a.owner.id}", json={"password": "lemon-5512"}, headers=shop_a.owner_h
    )
    assert r.status_code == 400
    assert (
        client.patch(
            f"{API}/users/{shop_a.owner.id}", json={"is_active": False}, headers=shop_a.owner_h
        ).status_code
        == 400
    )


def test_only_the_owner_manages_staff(client, shop_a):
    assert client.get(f"{API}/users", headers=shop_a.cashier_h).status_code == 403
    r = client.post(
        f"{API}/users",
        json={"name": "Sneaky", "phone": "9876500009", "role": "owner", "password": FIRST},
        headers=shop_a.cashier_h,
    )
    assert r.status_code == 403


def test_phone_numbers_are_unique(client, shop_a, shop_b):
    _new_staff(client, shop_a.owner_h)
    r = client.post(
        f"{API}/users",
        json={"name": "Again", "phone": "98765 00001", "password": FIRST},
        headers=shop_b.owner_h,
    )
    assert r.status_code == 409


@pytest.fixture
def device(client, shop_a):
    build_catalogue(client, shop_a)
    return FakeDevice(client, shop_a)


def test_bills_are_credited_to_who_rang_them_up(client, shop_a, shop_b, device):
    """Ravi bills offline, logs out; the owner logs in and the tablet syncs."""
    ravi = _new_staff(client, shop_a.owner_h)
    by_ravi = device.bill([("Masala tea", 1, [])])
    by_ravi["cashier_id"] = ravi["id"]
    unnamed = device.bill([("Masala tea", 1, [])])  # an older app: no cashier_id
    foreign = device.bill([("Masala tea", 1, [])])
    foreign["cashier_id"] = str(shop_b.cashier.id)  # not one of ours

    r = device.sync([by_ravi, unnamed, foreign], headers=shop_a.owner_h)
    assert [x["status"] for x in r.json()["results"]] == ["accepted"] * 3

    def cashier(bill):
        return client.get(f"{API}/bills/{bill['id']}", headers=shop_a.owner_h).json()["cashier_id"]

    assert cashier(by_ravi) == ravi["id"]
    assert cashier(unnamed) == str(shop_a.owner.id)  # whoever synced it
    assert cashier(foreign) == str(shop_a.owner.id)

    report = client.get(f"{API}/reports/sales", headers=shop_a.owner_h).json()
    assert {c["name"]: c["bills"] for c in report["by_cashier"]} == {
        "Ravi": 1,
        "Shop A owner": 2,
    }
    # Retrying exactly what was sent is still a harmless duplicate, with or without the key.
    again = device.sync([by_ravi, unnamed], headers=shop_a.owner_h).json()["results"]
    assert [x["status"] for x in again] == ["duplicate", "duplicate"]


def test_a_deactivated_cashiers_offline_bills_still_count_as_theirs(client, shop_a, device):
    ravi = _new_staff(client, shop_a.owner_h)
    bill = device.bill([("Masala tea", 1, [])])
    bill["cashier_id"] = ravi["id"]
    client.patch(
        f"{API}/users/{ravi['id']}", json={"is_active": False}, headers=shop_a.owner_h
    ).raise_for_status()
    device.sync([bill], headers=shop_a.owner_h).raise_for_status()
    got = client.get(f"{API}/bills/{bill['id']}", headers=shop_a.owner_h).json()
    assert got["cashier_id"] == ravi["id"]

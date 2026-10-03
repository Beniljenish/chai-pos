"""PHASE 2a GATE: bills sent the way a flaky device sends them (shuffled,
batched, every batch sent twice) end up stored exactly once, with gap-free
invoice numbers and stock deducted exactly once per bill."""

import random
from decimal import Decimal

import pytest

from tests.conftest import FakeDevice, build_catalogue

D = Decimal


@pytest.fixture
def setup(client, shop_a):
    cat = build_catalogue(client, shop_a)
    # A scaling modifier on juice, to exercise recipe x scale in stock deduction.
    large = client.post(
        "/api/v1/modifiers",
        json={"name": "Large", "price_delta_paise": 1000, "scale_factor": "1.5"},
        headers=shop_a.owner_h,
    ).json()
    client.put(
        f"/api/v1/menu-items/{cat.juice['id']}/modifiers",
        json={"modifier_ids": [large["id"]]},
        headers=shop_a.owner_h,
    )
    return cat, FakeDevice(client, shop_a)


def _sale_rows(client, shop, ingredient_id):
    rows = client.get(
        f"/api/v1/stock/{ingredient_id}/ledger?limit=1000", headers=shop.owner_h
    ).json()
    return [r for r in rows if r["reason"] == "sale"]


def test_twenty_bills_from_a_flaky_device_land_exactly_once(client, shop_a, setup):
    cat, device = setup
    rng = random.Random(7)

    bills, expect_decoction, expect_oranges = [], D(0), D(0)
    for _ in range(20):
        items = []
        if rng.random() < 0.8:
            q = rng.randint(1, 4)
            items.append(("Masala tea", q, ["Less sugar"] if rng.random() < 0.3 else []))
            expect_decoction += D(100) * q  # Less sugar can't add sugar back: no sugar row
        if not items or rng.random() < 0.5:
            q = rng.randint(1, 3)
            large = rng.random() < 0.5
            items.append(("Orange juice", q, ["Large"] if large else []))
            expect_oranges += (D("555.556") * (D("1.5") if large else 1) * q).quantize(D("0.001"))
        bills.append(device.bill(items, payment_mode=rng.choice(["cash", "upi", "card"])))

    # Network chaos: shuffled order, random batch sizes, every batch sent twice.
    order = bills[:]
    rng.shuffle(order)
    statuses: dict[str, list[str]] = {b["id"]: [] for b in bills}
    i = 0
    while i < len(order):
        batch = order[i : i + rng.randint(1, 7)]
        i += len(batch)
        for _attempt in range(2):
            r = device.sync(batch)
            assert r.status_code == 200, r.text
            for res in r.json()["results"]:
                statuses[res["id"]].append(res["status"])
    # ...and the whole outbox once more, as after an app restart
    for res in device.sync(bills[:50]).json()["results"]:
        statuses[res["id"]].append(res["status"])

    # Each bill: accepted exactly once, every retry a harmless duplicate.
    for history in statuses.values():
        assert history[0] == "accepted"
        assert set(history[1:]) == {"duplicate"}

    # A different bill reusing an id is refused, and the original is untouched.
    tampered = device.bill([("Masala tea", 9, [])], seq=99)
    tampered["id"] = bills[4]["id"]
    res = device.sync([tampered]).json()["results"][0]
    assert res == {**res, "status": "rejected", "reason": "id_reused_with_different_content"}

    stored = client.get("/api/v1/bills", headers=shop_a.owner_h).json()
    assert len(stored) == 20
    fy = bills[0]["invoice_no"].split("/")[1]
    assert sorted(b["invoice_no"] for b in stored) == [f"C1/{fy}/{n:06d}" for n in range(1, 21)]
    assert not any(b["totals_mismatch"] for b in stored)

    # Stock deducted exactly once per bill, by the pinned recipes.
    dec_rows = _sale_rows(client, shop_a, cat.decoction["id"])
    orange_rows = _sale_rows(client, shop_a, cat.oranges["id"])
    assert -sum(D(r["qty_delta"]) for r in dec_rows) == expect_decoction
    assert -sum(D(r["qty_delta"]) for r in orange_rows) == expect_oranges
    for rows in (dec_rows, orange_rows):
        refs = [r["ref_id"] for r in rows]
        assert len(refs) == len(set(refs))  # never two rows for one bill+ingredient
    assert _sale_rows(client, shop_a, cat.sugar["id"]) == []

"""PHASE 1 GATE: stock on hand is exactly the sum of the ledger, recipe versions
are pinned in time, and the ledger cannot be rewritten."""

import random
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import engine
from tests.conftest import build_catalogue

D = Decimal
Q = D("0.001")

# Mirrors build_catalogue's placeholder decoction recipe, written out independently.
DECOCTION_PER_BATCH = {"milk": D(2000), "tea_powder": D(60), "sugar": D(150)}
DECOCTION_YIELD = D(2200)


@pytest.fixture
def cat(client, shop_a):
    return build_catalogue(client, shop_a)


def _stock(client, shop) -> dict[str, Decimal]:
    rows = client.get("/api/v1/stock", headers=shop.owner_h).json()
    return {r["ingredient_id"]: D(r["on_hand"]) for r in rows}


def test_stock_on_hand_equals_independent_replay_of_200_random_movements(
    client: TestClient, shop_a, cat
):
    rng = random.Random(20261003)  # fixed seed: a failure is reproducible
    expected = {k: D(0) for k in ("milk", "sugar", "tea_powder", "oranges", "decoction")}
    packs = {
        "milk": [(u["id"], D(u["qty_in_base"])) for u in cat.milk["pack_units"]],
        "sugar": [(u["id"], D(u["qty_in_base"])) for u in cat.sugar["pack_units"]],
        "tea_powder": [(u["id"], D(u["qty_in_base"])) for u in cat.tea_powder["pack_units"]],
        "oranges": [],
    }
    ids = {k: getattr(cat, k)["id"] for k in expected}

    for _ in range(200):
        if rng.random() < 0.7:
            name = rng.choice(list(packs))
            chosen = [(pid, size, rng.randint(0, 4)) for pid, size in packs[name]]
            loose = D(rng.randint(0, 999_999)) / 1000
            total = sum((size * n for _, size, n in chosen), D(0)) + loose
            if total == 0:
                continue
            r = client.post(
                "/api/v1/stock-in",
                json={
                    "ingredient_id": ids[name],
                    "packs": [{"pack_unit_id": pid, "qty": str(n)} for pid, _, n in chosen if n],
                    "loose_qty": str(loose),
                    "confirm_large": True,
                },
                headers=shop_a.owner_h,
            )
            assert r.status_code == 201, r.text
            assert D(r.json()["base_qty"]) == total.quantize(Q)
            expected[name] += total
        else:
            # fractional sizes on purpose: 2200 x 0.333 = 732.6 catches any rounding bug
            batches = rng.choice([D("0.25"), D("0.333"), D(1), D("1.125"), D(2)])
            r = client.post(
                "/api/v1/prep-batches",
                json={"ingredient_id": ids["decoction"], "batches": str(batches)},
                headers=shop_a.cashier_h,
            )
            assert r.status_code == 201, r.text
            for name, per_batch in DECOCTION_PER_BATCH.items():
                expected[name] -= per_batch * batches
            expected["decoction"] += DECOCTION_YIELD * batches

    actual = _stock(client, shop_a)
    for name, qty in expected.items():
        assert actual[ids[name]] == qty.quantize(Q), name

    # ...and the per-ingredient ledger history adds up to the same number.
    for name in expected:
        rows = client.get(
            f"/api/v1/stock/{ids[name]}/ledger?limit=1000", headers=shop_a.owner_h
        ).json()
        assert sum((D(r["qty_delta"]) for r in rows), D(0)) == actual[ids[name]]


def test_recipe_versions_are_pinned_in_time(client: TestClient, shop_a, cat):
    url = f"/api/v1/menu-items/{cat.tea['id']}/recipe"
    v1 = client.get(url, headers=shop_a.owner_h).json()
    between = datetime.now(UTC).isoformat()

    r = client.put(
        url,
        json={"lines": [{"ingredient_id": cat.decoction["id"], "qty": "120"}]},
        headers=shop_a.owner_h,
    )
    assert r.status_code == 200 and r.json()["version"] == v1["version"] + 1

    assert client.get(url, headers=shop_a.owner_h).json()["lines"][0]["qty"] == "120.000"
    old = client.get(url, params={"at": between}, headers=shop_a.owner_h).json()
    assert old["id"] == v1["id"] and old["lines"][0]["qty"] == "100.000"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE stock_ledger SET qty_delta = 1",
        "DELETE FROM stock_ledger",
    ],
)
def test_ledger_rejects_update_and_delete_even_from_raw_sql(client, shop_a, cat, sql):
    client.post(
        "/api/v1/stock-in",
        json={"ingredient_id": cat.milk["id"], "loose_qty": "500"},
        headers=shop_a.owner_h,
    )
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
        conn.execute(text(sql))

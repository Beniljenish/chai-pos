import os

# Must be set before the app (and its engine) is imported.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://chai:chai@localhost:5432/chai_pos_test")
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789")

from dataclasses import dataclass  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.db.tenancy import mark_system  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Device, GstType, Role, Shop, User  # noqa: E402

PASSWORD = "correct-horse-1"


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    """Build the test schema with the real migrations, not create_all().
    That way the tests also prove the migrations work."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE shops CASCADE"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@dataclass
class ShopFixture:
    shop: Shop
    owner: User
    cashier: User
    device: Device
    owner_token: str
    cashier_token: str

    @property
    def owner_h(self) -> dict:
        return {"Authorization": f"Bearer {self.owner_token}"}

    @property
    def cashier_h(self) -> dict:
        return {"Authorization": f"Bearer {self.cashier_token}"}


_counter = {"n": 0}


def _phone() -> str:
    _counter["n"] += 1
    return f"9{_counter['n']:09d}"


def make_shop(client: TestClient, name: str) -> ShopFixture:
    db = mark_system(SessionLocal())
    # A regular-GST shop always has a GSTIN; this one is synthetic but has a
    # valid check digit and Tamil Nadu's state code.
    shop = Shop(name=name, gst_type=GstType.regular, gstin="33ABCDE1234F1Z7", state_code="33")
    db.add(shop)
    db.flush()
    owner = User(
        shop_id=shop.id,
        name=f"{name} owner",
        phone=_phone(),
        role=Role.owner,
        password_hash=hash_password(PASSWORD),
    )
    cashier = User(
        shop_id=shop.id,
        name=f"{name} cashier",
        phone=_phone(),
        role=Role.cashier,
        password_hash=hash_password(PASSWORD),
    )
    device = Device(shop_id=shop.id, name="Counter 1", code="C1")
    db.add_all([owner, cashier, device])
    db.commit()
    db.close()

    def token(u: User) -> str:
        r = client.post("/api/v1/auth/login", json={"phone": u.phone, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    return ShopFixture(shop, owner, cashier, device, token(owner), token(cashier))


@pytest.fixture
def shop_a(client) -> ShopFixture:
    return make_shop(client, "Shop A")


@pytest.fixture
def shop_b(client) -> ShopFixture:
    return make_shop(client, "Shop B")


@dataclass
class Catalogue:
    milk: dict
    sugar: dict
    tea_powder: dict
    oranges: dict
    decoction: dict
    tea: dict
    juice: dict
    less_sugar: dict


def build_catalogue(client: TestClient, shop: ShopFixture) -> Catalogue:
    """A small placeholder catalogue built through the public API, as an owner would."""
    h = shop.owner_h

    def post(path, body):
        r = client.post(f"/api/v1{path}", json=body, headers=h)
        assert r.status_code == 201, r.text
        return r.json()

    def put(path, body):
        r = client.put(f"/api/v1{path}", json=body, headers=h)
        assert r.status_code == 200, r.text
        return r.json()

    milk = post(
        "/ingredients",
        {
            "name": "Milk",
            "base_unit": "ml",
            "pack_units": [
                {"name": "packet", "qty_in_base": "500"},
                {"name": "crate", "qty_in_base": "12000"},
            ],
        },
    )
    sugar = post(
        "/ingredients",
        {
            "name": "Sugar",
            "base_unit": "g",
            "pack_units": [{"name": "bag", "qty_in_base": "1000"}],
        },
    )
    tea_powder = post(
        "/ingredients",
        {
            "name": "Tea powder",
            "base_unit": "g",
            "pack_units": [{"name": "pouch", "qty_in_base": "250"}],
        },
    )
    oranges = post("/ingredients", {"name": "Oranges", "base_unit": "g", "tolerance_bp": 800})
    decoction = post("/ingredients", {"name": "Tea decoction", "kind": "prep", "base_unit": "ml"})
    put(
        f"/ingredients/{decoction['id']}/recipe",
        {
            "yield_qty": "2200",
            "lines": [
                {"ingredient_id": milk["id"], "qty": "2000"},
                {"ingredient_id": tea_powder["id"], "qty": "60"},
                {"ingredient_id": sugar["id"], "qty": "150"},
            ],
        },
    )
    tea = post("/menu-items", {"name": "Masala tea", "price_paise": 2000})
    put(
        f"/menu-items/{tea['id']}/recipe",
        {"lines": [{"ingredient_id": decoction["id"], "qty": "100"}]},
    )
    juice = post("/menu-items", {"name": "Orange juice", "category": "Juice", "price_paise": 6000})
    put(
        f"/menu-items/{juice['id']}/recipe",
        {
            "juice_yield": {
                "ingredient_id": oranges["id"],
                "ml_per_kg": "450",
                "portion_ml": "250",
            },
        },
    )
    less_sugar = post(
        "/modifiers",
        {
            "name": "Less sugar",
            "lines": [{"ingredient_id": sugar["id"], "qty_delta": "-5"}],
        },
    )
    put(f"/menu-items/{tea['id']}/modifiers", {"modifier_ids": [less_sugar["id"]]})
    return Catalogue(milk, sugar, tea_powder, oranges, decoction, tea, juice, less_sugar)


class FakeDevice:
    """Behaves like the billing app: reads /catalogue, numbers invoices per device
    and financial year, and computes printed totals with the shared GST code."""

    def __init__(self, client: TestClient, shop: ShopFixture, device_id=None, code="C1"):
        from app.services.billing import financial_year  # local: avoid import cycles

        self._fy = financial_year
        self.client, self.shop = client, shop
        self.device_id = str(device_id or shop.device.id)
        self.code = code
        self.seq = 0
        self.catalogue = client.get("/api/v1/catalogue", headers=shop.cashier_h).json()

    def refresh_catalogue(self):
        self.catalogue = self.client.get("/api/v1/catalogue", headers=self.shop.cashier_h).json()

    def bill(self, items, *, payment_mode="cash", sold_at=None, seq=None) -> dict:
        """items: [(menu item name, qty, [modifier names])]"""
        import uuid as _uuid
        from datetime import UTC
        from datetime import datetime as _dt

        from app.core.time import business_date
        from app.services.gst import LineIn, compute_bill

        sold_at = sold_at or _dt.now(UTC)
        if seq is None:
            self.seq += 1
            seq = self.seq
        menu = {m["name"]: m for m in self.catalogue["menu_items"]}
        mods = {m["name"]: m for m in self.catalogue["modifiers"]}
        gst_type = GstType(self.catalogue["shop"]["gst_type"])

        lines = []
        for name, qty, mod_names in items:
            item = menu[name]
            snaps = [
                {
                    "modifier_id": mods[n]["id"],
                    "name": n,
                    "price_delta_paise": mods[n]["price_delta_paise"],
                    "scale_factor": mods[n]["scale_factor"],
                    "lines": [
                        {"ingredient_id": ml["ingredient_id"], "qty_delta": ml["qty_delta"]}
                        for ml in mods[n]["lines"]
                    ],
                }
                for n in mod_names
            ]
            lines.append(
                {
                    "menu_item_id": item["id"],
                    "recipe_id": item["recipe"]["id"] if item["recipe"] else None,
                    "name": name,
                    "unit_price_paise": item["price_paise"],
                    "qty": qty,
                    "gst_rate_bp": item["gst_rate_bp"],
                    "tax_inclusive": item["tax_inclusive"],
                    "modifiers": snaps,
                }
            )
        totals = compute_bill(
            [
                LineIn(
                    ln["unit_price_paise"],
                    ln["qty"],
                    ln["gst_rate_bp"],
                    ln["tax_inclusive"],
                    tuple(m["price_delta_paise"] for m in ln["modifiers"]),
                )
                for ln in lines
            ],
            gst_type,
        )
        for ln, lt in zip(lines, totals.lines, strict=True):
            ln["totals"] = {
                "gross": lt.gross,
                "taxable": lt.taxable,
                "cgst": lt.cgst,
                "sgst": lt.sgst,
                "total": lt.total,
            }
        fy = self._fy(business_date(sold_at))
        return {
            "id": str(_uuid.uuid4()),
            "local_seq": seq,
            "invoice_no": f"{self.code}/{fy}/{seq:06d}",
            "sold_at": sold_at.isoformat(),
            "payment_mode": payment_mode,
            "gst_type": gst_type.value,
            "lines": lines,
            "totals": {
                "taxable": totals.taxable,
                "cgst": totals.cgst,
                "sgst": totals.sgst,
                "subtotal": totals.subtotal,
                "round_off": totals.round_off,
                "total": totals.total,
            },
        }

    def sync(self, bills: list[dict], headers=None):
        return self.client.post(
            "/api/v1/sync/bills",
            json={"device_id": self.device_id, "bills": bills},
            headers=headers or self.shop.cashier_h,
        )

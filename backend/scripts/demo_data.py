"""Four weeks of realistic demo data for one shop (README, "Demo data").

Everything goes through the real API in-process, with the clock moved through
the weeks (time-machine), so the data obeys every rule a tablet would meet:
GST per line, stock deducted by recipe version, shifts and drawers, day-end
counts and variance, running orders and KOTs, khata, purchase orders.

It writes to DATABASE_URL, which must be an EMPTY local database (migrated).
The staging load is a data-only dump of that database (see README).

    DEMO_KEEP=keep.json DATABASE_URL=... JWT_SECRET=... python -m scripts.demo_data

keep.json names the shop and the logins to reuse, so their ids match staging
(passwords are not copied: local rows get a random one):
    {"shop_id": "...", "users": [{"id": "...", "name": "...", "role": "owner"}]}
The first owner in the list does the owner's work in the data.

PLACEHOLDER: names, prices, suppliers and phone numbers are invented.
"""

import json
import logging
import os
import random
import secrets
import sys
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.main import app
from app.models import Bill, GstType, Role, Shop, User
from app.services.billing import financial_year
from app.services.gst import LineIn, compute_bill

IST = ZoneInfo("Asia/Kolkata")
API = "/api/v1"
DAYS = 28  # tests use fewer
rnd = random.Random(20261004)


# ---------------------------------------------------------------- plumbing
class Api:
    """The API at a chosen moment, as a chosen person."""

    def __init__(self, shop_id: uuid.UUID):
        self.client = TestClient(app)
        self.shop_id = shop_id
        self.now = datetime.now(UTC)

    def at(self, when: datetime) -> "Api":
        self.now = when
        return self

    def call(self, method: str, path: str, who: dict, body=None, ok=(200, 201, 204)):
        with time_machine.travel(self.now, tick=False):
            token = create_access_token(user_id=who["id"], shop_id=self.shop_id, role=who["role"])
            r = self.client.request(
                method, API + path, json=body, headers={"Authorization": f"Bearer {token}"}
            )
        if r.status_code not in ok:
            raise RuntimeError(f"{method} {path} at {self.now}: {r.status_code} {r.text[:400]}")
        return r.json() if r.content else None

    def post(self, path, who, body=None, **kw):
        return self.call("POST", path, who, body, **kw)

    def put(self, path, who, body=None):
        return self.call("PUT", path, who, body)

    def patch(self, path, who, body=None):
        return self.call("PATCH", path, who, body)

    def get(self, path, who):
        return self.call("GET", path, who)


def ist(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), IST).astimezone(UTC)


def uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- the shop
def make_shop(keep: dict) -> tuple[dict, dict]:
    """The shop and its kept logins, with the same ids as staging."""
    db = mark_system(SessionLocal())
    shop = Shop(
        id=uuid.UUID(keep["shop_id"]),
        name="Jamun Tea & Juice (demo)",
        gst_type=GstType.regular,
        gstin="33ABCDE1234F1Z7",  # synthetic, valid check digit, Tamil Nadu
        state_code="33",
        address="Demo address, T. Nagar, Chennai, Tamil Nadu",
        invoice_prefix="JT",
    )
    db.add(shop)
    db.flush()
    people = {}
    for n, u in enumerate(keep["users"]):
        db.add(
            User(
                id=uuid.UUID(u["id"]),
                shop_id=shop.id,
                name=u["name"],
                phone=f"90000{n:05d}",  # local only: users are not in the dump
                role=Role(u["role"]),
                password_hash=hash_password(secrets.token_urlsafe(16)),
            )
        )
        people.setdefault(u["role"], []).append({"id": u["id"], "role": u["role"]})
    db.commit()
    db.close()
    return {"id": keep["shop_id"]}, people


# Ingredients: name, unit, packs, tolerance, kind, reorder level, scales with size
RAW = [
    ("Milk", "ml", [("packet", 500), ("crate", 12000)], 800, "8000", True),
    ("Tea powder", "g", [("pouch", 250), ("kg bag", 1000)], 300, "800", True),
    ("Coffee powder", "g", [("pouch", 500)], 300, "400", True),
    ("Sugar", "g", [("kg bag", 1000)], 300, "3000", True),
    ("Ginger", "g", [], 800, "250", True),
    ("Cardamom", "g", [("pack", 50)], 500, "30", True),
    ("Lemon", "piece", [], 500, "30", False),
    ("Mint leaves", "g", [("bunch", 100)], 1000, "100", True),
    ("Oranges", "g", [], 800, "3000", True),
    ("Watermelon", "g", [], 1000, "4000", True),
    ("Pineapple", "g", [], 1000, "2000", True),
    ("Mango pulp", "ml", [("tin", 850)], 300, "850", True),
    ("Rose syrup", "ml", [("bottle", 750)], 300, "300", True),
    ("Badam mix", "g", [("jar", 500)], 300, "200", True),
    ("Malt drink powder", "g", [("jar", 500)], 300, "300", True),
    ("Soda", "piece", [("crate", 24)], 200, "24", False),
    ("Paper cup", "piece", [("sleeve", 50), ("box", 1000)], 200, "300", False),
    ("Juice cup with lid", "piece", [("sleeve", 50)], 200, "100", False),
    ("Samosa", "piece", [("tray", 30)], 300, "0", False),
    ("Veg puff", "piece", [("tray", 20)], 300, "0", False),
    ("Bun", "piece", [("pack", 6)], 300, "12", False),
    ("Butter", "g", [("block", 500)], 500, "100", True),
    ("Osmania biscuit", "piece", [("box", 50)], 300, "50", False),
    ("Water bottle", "piece", [("case", 24)], 100, "24", False),
]
# Purchase price per base unit, in paise (milk ₹56/L, tea ₹520/kg, ...)
COST = {
    "Milk": D("5.6"),
    "Tea powder": D("52"),
    "Coffee powder": D("90"),
    "Sugar": D("4.6"),
    "Ginger": D("14"),
    "Cardamom": D("320"),
    "Lemon": D("500"),
    "Mint leaves": D("8"),
    "Oranges": D("8"),
    "Watermelon": D("2.5"),
    "Pineapple": D("6"),
    "Mango pulp": D("22"),
    "Rose syrup": D("24"),
    "Badam mix": D("110"),
    "Malt drink powder": D("60"),
    "Soda": D("1200"),
    "Paper cup": D("70"),
    "Juice cup with lid": D("250"),
    "Samosa": D("700"),
    "Veg puff": D("1100"),
    "Bun": D("800"),
    "Butter": D("56"),
    "Osmania biscuit": D("400"),
    "Water bottle": D("1000"),
}
# Menu: name, category, price ₹, recipe [(ingredient, qty)], juice (fruit, ml/kg, portion)
MENU = [
    ("Masala tea", "Tea", 20, [("Tea decoction", 100), ("Ginger", 1), ("Paper cup", 1)], None),
    ("Ginger tea", "Tea", 20, [("Tea decoction", 100), ("Ginger", 4), ("Paper cup", 1)], None),
    (
        "Elaichi tea",
        "Tea",
        22,
        [("Tea decoction", 100), ("Cardamom", "0.5"), ("Paper cup", 1)],
        None,
    ),
    (
        "Lemon tea",
        "Tea",
        15,
        [("Tea powder", 3), ("Sugar", 10), ("Lemon", "0.25"), ("Paper cup", 1)],
        None,
    ),
    ("Black tea", "Tea", 12, [("Tea powder", 3), ("Sugar", 10), ("Paper cup", 1)], None),
    ("Filter coffee", "Coffee", 25, [("Coffee decoction", 110), ("Paper cup", 1)], None),
    ("Malt milk", "Coffee", 30, [("Milk", 150), ("Malt drink powder", 20), ("Paper cup", 1)], None),
    (
        "Badam milk",
        "Coffee",
        35,
        [("Milk", 180), ("Badam mix", 15), ("Sugar", 10), ("Paper cup", 1)],
        None,
    ),
    (
        "Rose milk",
        "Juice",
        35,
        [("Milk", 200), ("Rose syrup", 30), ("Juice cup with lid", 1)],
        None,
    ),
    ("Orange juice", "Juice", 60, [("Juice cup with lid", 1)], ("Oranges", 450, 250)),
    ("Watermelon juice", "Juice", 50, [("Juice cup with lid", 1)], ("Watermelon", 600, 300)),
    (
        "Pineapple juice",
        "Juice",
        60,
        [("Sugar", 15), ("Juice cup with lid", 1)],
        ("Pineapple", 500, 250),
    ),
    (
        "Mango milkshake",
        "Juice",
        70,
        [("Mango pulp", 80), ("Milk", 150), ("Sugar", 10), ("Juice cup with lid", 1)],
        None,
    ),
    (
        "Fresh lime soda",
        "Juice",
        30,
        [("Lemon", 1), ("Soda", 1), ("Sugar", 15), ("Juice cup with lid", 1)],
        None,
    ),
    (
        "Mint lime",
        "Juice",
        35,
        [("Lemon", 1), ("Mint leaves", 5), ("Sugar", 20), ("Juice cup with lid", 1)],
        None,
    ),
    ("Samosa", "Snacks", 15, [("Samosa", 1)], None),
    ("Veg puff", "Snacks", 25, [("Veg puff", 1)], None),
    ("Bun butter jam", "Snacks", 30, [("Bun", 1), ("Butter", 10)], None),
    ("Osmania biscuit", "Snacks", 10, [("Osmania biscuit", 1)], None),
    ("Water bottle", "Snacks", 20, [("Water bottle", 1)], None),
]
# How often each item sells, morning-to-night weights
POPULAR = {
    "Masala tea": 30,
    "Ginger tea": 14,
    "Elaichi tea": 8,
    "Lemon tea": 6,
    "Black tea": 4,
    "Filter coffee": 14,
    "Malt milk": 3,
    "Badam milk": 3,
    "Rose milk": 3,
    "Orange juice": 4,
    "Watermelon juice": 4,
    "Pineapple juice": 2,
    "Mango milkshake": 3,
    "Fresh lime soda": 4,
    "Mint lime": 3,
    "Samosa": 10,
    "Veg puff": 5,
    "Bun butter jam": 4,
    "Osmania biscuit": 8,
    "Water bottle": 3,
}
SNACKS = {"Samosa", "Veg puff", "Bun butter jam", "Osmania biscuit"}
CUSTOMERS = [
    ("Ramesh K", "9000010001"),
    ("Lakshmi S", "9000010002"),
    ("Arjun M", "9000010003"),
    ("Fathima B", "9000010004"),
    ("Senthil P", "9000010005"),
    ("Divya R", "9000010006"),
    ("Office: 2nd floor", "9000010007"),
    ("Auto stand", "9000010008"),
    ("Karthik V", "9000010009"),
    ("Meena G", "9000010010"),
]
TAKEAWAY_NAMES = ["Suresh", "Anitha", "Vignesh", "Kavya", "Prakash", "Nisha", "Hari", "Deepa"]


def build_catalogue(api: Api, owner: dict) -> dict:
    ids: dict[str, dict] = {}
    for name, unit, packs, tol, reorder, scales in RAW:
        body = {
            "name": name,
            "base_unit": unit,
            "tolerance_bp": tol,
            "scales_with_size": scales,
            "pack_units": [{"name": n, "qty_in_base": str(q)} for n, q in packs],
        }
        if reorder != "0":
            body["reorder_level"] = reorder
        if name in {"Samosa", "Veg puff"}:  # bought in each morning, counted each night
            body["count_frequency"] = "daily"
        ids[name] = api.post("/ingredients", owner, body)
    for prep, lines, yield_qty in (
        ("Tea decoction", [("Milk", 2000), ("Tea powder", 60), ("Sugar", 150)], 2200),
        ("Coffee decoction", [("Milk", 2000), ("Coffee powder", 80), ("Sugar", 150)], 2200),
    ):
        ids[prep] = api.post(
            "/ingredients",
            owner,
            {"name": prep, "kind": "prep", "base_unit": "ml", "tolerance_bp": 500},
        )
        api.put(
            f"/ingredients/{ids[prep]['id']}/recipe",
            owner,
            {
                "yield_qty": str(yield_qty),
                "lines": [{"ingredient_id": ids[i]["id"], "qty": str(q)} for i, q in lines],
            },
        )

    menu = {}
    for name, cat, rupees, lines, juice in MENU:
        m = api.post(
            "/menu-items", owner, {"name": name, "category": cat, "price_paise": rupees * 100}
        )
        body = {"lines": [{"ingredient_id": ids[i]["id"], "qty": str(q)} for i, q in lines]}
        if juice:
            fruit, per_kg, portion = juice
            body["juice_yield"] = {
                "ingredient_id": ids[fruit]["id"],
                "ml_per_kg": str(per_kg),
                "portion_ml": str(portion),
            }
        api.put(f"/menu-items/{m['id']}/recipe", owner, body)
        menu[name] = m

    def modifier(name, items, price=0, scale="1", lines=()):
        m = api.post(
            "/modifiers",
            owner,
            {
                "name": name,
                "price_delta_paise": price,
                "scale_factor": scale,
                "lines": [{"ingredient_id": ids[i]["id"], "qty_delta": str(q)} for i, q in lines],
            },
        )
        api.put(
            f"/modifiers/{m['id']}/menu-items",
            owner,
            {"menu_item_ids": [menu[i]["id"] for i in items]},
        )

    teas = ["Masala tea", "Ginger tea", "Elaichi tea", "Filter coffee", "Malt milk", "Badam milk"]
    modifier("Less sugar", teas + ["Lemon tea", "Black tea"], lines=[("Sugar", -5)])
    modifier(
        "No sugar",
        teas + ["Lemon tea", "Black tea", "Fresh lime soda", "Mint lime"],
        lines=[("Sugar", -10)],
    )
    modifier(
        "Large",
        teas
        + ["Rose milk", "Orange juice", "Watermelon juice", "Pineapple juice", "Mango milkshake"],
        price=1000,
        scale="1.5",
    )
    modifier("Extra ginger", ["Masala tea", "Ginger tea"], price=200, lines=[("Ginger", 3)])
    modifier("Strong", ["Masala tea", "Filter coffee"], lines=[("Tea powder", 1)])
    modifier(
        "No ice",
        ["Orange juice", "Watermelon juice", "Pineapple juice", "Fresh lime soda", "Mint lime"],
    )
    return ids


def build_floor(api: Api, owner: dict) -> dict:
    tables = {}
    for area, names, seats in (
        ("Hall", ["T1", "T2", "T3", "T4", "T5", "T6"], 4),
        ("Family", ["F1", "F2", "F3"], 6),
        ("Outdoor", ["P1", "P2", "P3", "P4"], 2),
    ):
        a = api.post("/areas", owner, {"name": area})
        for n in names:
            tables[n] = api.post("/tables", owner, {"area_id": a["id"], "name": n, "seats": seats})
    return tables


# ---------------------------------------------------------------- a tablet
class Tablet:
    """Numbers invoices per financial year and prices bills with the shared GST code,
    like the app does."""

    def __init__(self, api: Api, device: dict, owner: dict):
        self.api, self.device = api, device
        self.seq: dict[str, int] = {}
        self.kot = 0
        self.outbox: list[dict] = []
        self.events: list[dict] = []
        self.shift_ops: list[dict] = []
        self.shift: str | None = None
        self.cat = api.get("/catalogue", owner)
        self.menu = {m["name"]: m for m in self.cat["menu_items"]}
        self.mods = {m["name"]: m for m in self.cat["modifiers"]}

    def snap(self, name):
        m = self.mods[name]
        return {
            "modifier_id": m["id"],
            "name": name,
            "price_delta_paise": m["price_delta_paise"],
            "scale_factor": m["scale_factor"],
            "lines": [
                {"ingredient_id": x["ingredient_id"], "qty_delta": x["qty_delta"]}
                for x in m["lines"]
            ],
        }

    def bill(
        self,
        items,
        at,
        cashier,
        *,
        mode="cash",
        parts=None,
        customer=None,
        discount=0,
        reason="",
        order_id=None,
    ):
        gst_type = GstType(self.cat["shop"]["gst_type"])
        lines = []
        for name, qty, mods in items:
            it = self.menu[name]
            lines.append(
                {
                    "menu_item_id": it["id"],
                    "recipe_id": it["recipe"]["id"] if it["recipe"] else None,
                    "name": name,
                    "unit_price_paise": it["price_paise"],
                    "qty": qty,
                    "gst_rate_bp": it["gst_rate_bp"],
                    "tax_inclusive": it["tax_inclusive"],
                    "modifiers": [self.snap(n) for n in mods],
                }
            )
        totals = compute_bill(
            [
                LineIn(
                    x["unit_price_paise"],
                    x["qty"],
                    x["gst_rate_bp"],
                    x["tax_inclusive"],
                    tuple(m["price_delta_paise"] for m in x["modifiers"]),
                    0,
                )
                for x in lines
            ],
            gst_type,
            discount,
        )
        for x, t in zip(lines, totals.lines, strict=True):
            x["totals"] = {
                "gross": t.gross,
                "taxable": t.taxable,
                "cgst": t.cgst,
                "sgst": t.sgst,
                "total": t.total,
            }
            if t.discount:
                x["totals"]["discount"] = t.discount
        fy = financial_year(at.astimezone(IST).date())
        self.seq[fy] = self.seq.get(fy, 0) + 1
        b = {
            "id": uid(),
            "local_seq": self.seq[fy],
            "invoice_no": f"{self.device['code']}/{fy}/{self.seq[fy]:06d}",
            "sold_at": at.isoformat(),
            "payment_mode": mode,
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
            "cashier_id": cashier["id"],
        }
        if totals.discount:
            b["totals"]["discount"] = totals.discount
            b["bill_discount_paise"] = discount
            b["discount_reason"] = reason
        if self.shift:
            b["shift_id"] = self.shift
        if order_id:
            b["order_id"] = order_id
        if parts:
            b["payment_parts"] = [{"mode": m, "paise": p} for m, p in parts(totals.total)]
        if customer:
            b["customer"] = customer
        self.outbox.append(b)
        return b

    def event(self, order_id, kind, at, by, data=None):
        self.events.append(
            {
                "id": uid(),
                "order_id": order_id,
                "kind": kind,
                "at": at.isoformat(),
                "by": by["id"],
                "data": data or {},
            }
        )

    def kot_line(self, name, qty, mods=(), note=""):
        it = self.menu[name]
        return {
            "line_id": uid(),
            "menu_item_id": it["id"],
            "name": name,
            "qty": qty,
            "unit_price_paise": it["price_paise"],
            "gst_rate_bp": it["gst_rate_bp"],
            "tax_inclusive": it["tax_inclusive"],
            "modifiers": [self.snap(n) for n in mods],
            "note": note,
        }

    def sync(self, who):
        """Shifts first, then order events, then bills: the app's order. Only what
        has happened by now (a tablet cannot send the future)."""
        dev = self.device["id"]

        def due(rows, key):
            now = self.api.now
            ready = [x for x in rows if datetime.fromisoformat(x[key]) <= now]
            return ready, [x for x in rows if datetime.fromisoformat(x[key]) > now]

        for path, attr, key, field, size in (
            ("/sync/shifts", "shift_ops", "at", "ops", 100),
            ("/sync/orders", "events", "at", "events", 200),
            ("/sync/bills", "outbox", "sold_at", "bills", 50),
        ):
            ready, later = due(getattr(self, attr), key)
            setattr(self, attr, later)
            ready.sort(key=lambda x: x[key])
            for i in range(0, len(ready), size):
                r = self.api.post(path, who, {"device_id": dev, field: ready[i : i + size]})
                bad = [x for x in r["results"] if x["status"] == "rejected"]
                if bad:
                    raise RuntimeError(f"{path} refused: {bad}")


# ---------------------------------------------------------------- one day
def pick_items(hour: int) -> list[tuple[str, int, list[str]]]:
    weights = dict(POPULAR)
    if 11 <= hour <= 17:  # afternoon: juices
        for k in (
            "Orange juice",
            "Watermelon juice",
            "Pineapple juice",
            "Mango milkshake",
            "Fresh lime soda",
            "Mint lime",
            "Rose milk",
        ):
            weights[k] *= 3
    names = list(weights)
    out = []
    for _ in range(rnd.choices([1, 2, 3, 4], [55, 28, 12, 5])[0]):
        name = rnd.choices(names, [weights[n] for n in names])[0]
        if any(o[0] == name for o in out):
            continue
        mods = []
        it_mods = MOD_MAP.get(name, [])
        for m, p in (
            ("Less sugar", 0.12),
            ("No sugar", 0.04),
            ("Large", 0.1),
            ("Extra ginger", 0.06),
            ("Strong", 0.05),
            ("No ice", 0.1),
        ):
            if (
                m in it_mods
                and rnd.random() < p
                and not ({"Less sugar", "No sugar"} & set(mods) and "sugar" in m)
            ):
                mods.append(m)
        qty = (
            rnd.choices([1, 2, 3], [70, 22, 8])[0]
            if name not in SNACKS
            else rnd.choices([1, 2, 4], [60, 30, 10])[0]
        )
        out.append((name, qty, mods))
    return out


MOD_MAP: dict[str, list[str]] = {}

HOURLY = {
    6: 9,
    7: 15,
    8: 16,
    9: 12,
    10: 8,
    11: 6,
    12: 6,
    13: 7,
    14: 6,
    15: 8,
    16: 12,
    17: 14,
    18: 13,
    19: 10,
    20: 7,
    21: 4,
}


def payment():
    r = rnd.random()
    if r < 0.52:
        return "cash", None
    if r < 0.90:
        return "upi", None
    if r < 0.96:
        return "card", None
    return "split", lambda total: [
        ("cash", total // 2 // 100 * 100 or 100),
        ("upi", total - (total // 2 // 100 * 100 or 100)),
    ]


def simulate(api: Api, keep_people: dict, ids: dict, tables: dict) -> None:
    owner = keep_people["owner"][0]
    staff_kept = keep_people.get("cashier", [])
    today = datetime.now(IST).date()
    start = today - timedelta(days=DAYS)
    api.at(ist(start - timedelta(days=1), 9))

    # Settings, staff, tablets, suppliers
    api.patch(
        "/shop",
        owner,
        {
            "cash_shifts": True,
            "max_discount_bp": 1000,
            "email_each_bill": False,
            "email_day_end": False,
            "email_daily": False,
            "email_weekly": False,
        },
    )
    staff = []
    for name, phone in (
        ("Ravi", "9000020001"),
        ("Priya", "9000020002"),
        ("Arun (waiter)", "9000020003"),
    ):
        u = api.post(
            "/users",
            owner,
            {
                "name": name,
                "phone": phone,
                "role": "cashier",
                "password": secrets.token_urlsafe(12),
            },
        )
        staff.append({"id": u["id"], "role": "cashier", "name": name})
    ravi, priya, arun = staff
    # They work in the simulation, so they act as if they had set their own
    # password. The staging load marks them "must change" again (README).
    db = mark_system(SessionLocal())
    for u in db.scalars(select(User).where(User.id.in_([x["id"] for x in staff]))):
        u.must_change_password = False
    db.commit()
    db.close()
    cashiers = [ravi, priya] + staff_kept[:1]
    c1 = api.post("/devices", owner, {"name": "Counter 1"})
    c2 = api.post("/devices", owner, {"name": "Counter 2"})
    w1 = api.post("/devices", owner, {"name": "Waiter phone"})
    suppliers = {
        n: api.post("/suppliers", owner, {"name": n, "phone": p, "note": note})
        for n, p, note in (
            ("Sri Murugan Milk Agency", "9000030001", "Milk crates at 5:30 am"),
            ("Lakshmi Tea Traders", "9000030002", "Tea, coffee, sugar, cardamom"),
            ("Selvam Fruits, Koyambedu", "9000030003", "Fruit every other day"),
            ("Ganesh Disposables", "9000030004", "Cups and lids"),
            ("Anand Bakery", "9000030005", "Samosa, puff, bun: daily"),
        )
    }
    cat = api.get("/catalogue", owner)
    mod_names = {m["id"]: m["name"] for m in cat["modifiers"]}
    for m in cat["menu_items"]:
        MOD_MAP[m["name"]] = [mod_names[x] for x in m.get("modifier_ids", [])]

    t1, t2, tw = Tablet(api, c1, owner), Tablet(api, c2, owner), Tablet(api, w1, owner)

    # Opening counts: what was on the shelf the morning before the first day
    api.at(ist(start, 5, 30))
    opening = {
        "Milk": 30000,
        "Tea powder": 2000,
        "Coffee powder": 1000,
        "Sugar": 8000,
        "Ginger": 500,
        "Cardamom": 60,
        "Lemon": 60,
        "Mint leaves": 200,
        "Oranges": 6000,
        "Watermelon": 8000,
        "Pineapple": 4000,
        "Mango pulp": 1700,
        "Rose syrup": 750,
        "Badam mix": 500,
        "Malt drink powder": 500,
        "Soda": 48,
        "Paper cup": 1500,
        "Juice cup with lid": 300,
        "Samosa": 0,
        "Veg puff": 0,
        "Bun": 12,
        "Butter": 500,
        "Osmania biscuit": 100,
        "Water bottle": 48,
    }
    for name, q in opening.items():
        api.post("/stock/opening", owner, {"ingredient_id": ids[name]["id"], "loose_qty": str(q)})

    def on_hand():
        return {s["name"]: D(s["on_hand"]) for s in api.get("/stock", owner)}

    def stock_in(name, qty, supplier):
        api.post(
            "/stock-in",
            owner,
            {
                "ingredient_id": ids[name]["id"],
                "loose_qty": str(qty),
                "cost_paise": int(D(qty) * COST[name] * D(rnd.uniform(0.96, 1.05))),
                "supplier": supplier,
                "confirm_large": True,
            },
        )

    def po(supplier, lines, receive_at=None, note=""):
        body = {
            "supplier_id": suppliers[supplier]["id"],
            "note": note,
            "lines": [
                {
                    "ingredient_id": ids[n]["id"],
                    "qty": str(q),
                    "expected_cost_paise": int(D(q) * COST[n]),
                }
                for n, q in lines
            ],
        }
        p = api.post("/purchase-orders", owner, body)
        if receive_at:
            api.at(receive_at)
            got = [
                {
                    "line_id": ln["id"],
                    "qty": str(D(ln["qty"]) * (D(1) if rnd.random() < 0.8 else D("0.9"))),
                    "cost_paise": int(D(ln["expected_cost_paise"]) * D(rnd.uniform(0.97, 1.04))),
                }
                for ln in p["lines"]
            ]
            api.post(f"/purchase-orders/{p['id']}/receive", owner, {"lines": got})
        return p

    customers = [{"id": uid(), "phone": p, "name": n} for n, p in CUSTOMERS]
    owed = {c["id"]: 0 for c in customers}

    for day_no in range(DAYS + 1):
        d = start + timedelta(days=day_no)
        is_today = d == today
        weekend = d.weekday() >= 5
        busy = (1.35 if weekend else 1.0) * rnd.uniform(0.85, 1.15)
        now_ist = datetime.now(IST)

        # Buying, as an owner does it: milk and bakery every morning, fruit three
        # times a week, dry goods on Tuesday, disposables on Thursday, and a
        # top-up from the shop next door when something is about to run out.
        api.at(ist(d, 5, 45))
        have, use = on_hand(), daily_use(d)

        def short(group, days, use=use, busy=busy, have=have):
            return [
                (n, need)
                for n in group
                if (need := round_up(n, use[n] * D(days) * D(busy) - have[n])) > 0
            ]

        for n, q in short(["Milk"], 1.15) + short(["Samosa", "Veg puff", "Bun"], 1.1):
            stock_in(n, q, "Sri Murugan Milk Agency" if n == "Milk" else "Anand Bakery")
        if d.weekday() in (0, 2, 4):
            api.at(ist(d, 7, 30))
            lines = short(FRUIT, 3.3 if d.weekday() == 4 else 2.4)
            if lines:
                po("Selvam Fruits, Koyambedu", lines, receive_at=ist(d, 8, 0))
        if d.weekday() == 1:
            api.at(ist(d, 10, 0))
            lines = short(DRY, 8)
            if lines:
                po("Lakshmi Tea Traders", lines, receive_at=ist(d, 15, 0))
        if d.weekday() == 3:
            api.at(ist(d, 11, 0))
            lines = short(DISPOSABLES, 8)
            if lines:
                po("Ganesh Disposables", lines, receive_at=ist(d, 12, 0))
        api.at(ist(d, 9, 30))
        have = on_hand()
        topup = short(FRUIT + DRY + DISPOSABLES, 1.6, have=have)
        for n, q in topup if d.weekday() not in (1, 3) else []:
            if have[n] < use[n] * D(busy):
                stock_in(n, q, "Local shop")

        # Shifts: Ravi on Counter 1 from 6, Priya on Counter 2 from 8 (Counter 2 only on busy days)
        morning, evening = rnd.choice(cashiers), rnd.choice(cashiers)
        open_c2 = weekend or rnd.random() < 0.5
        drawers = [(t1, morning, ist(d, 6, 0))] + ([(t2, priya, ist(d, 8, 0))] if open_c2 else [])
        for tab, who, at in drawers:
            tab.shift = uid()
            tab.shift_ops.append(
                {
                    "op": "open",
                    "id": tab.shift,
                    "at": at.isoformat(),
                    "opening_float_paise": 50000,
                    "cashier_id": who["id"],
                }
            )
            tab.who = who

        def make_prep(at, name, min_ml):
            api.at(at)
            h = on_hand()[name]
            if h < min_ml:
                api.post(
                    "/prep-batches",
                    owner,
                    {
                        "ingredient_id": ids[name]["id"],
                        "batches": str(int((min_ml - h) // 2200) + 1),
                    },
                )

        last_hour = 21
        if is_today:
            last_hour = min(21, now_ist.hour - 1)
        for hour in range(6, last_hour + 1):
            if hour == 14:
                # A busy day can outrun the morning's buying: the owner checks
                # again after lunch and fetches what will not last the evening.
                api.at(ist(d, 14, 0))
                have = on_hand()
                for n in FRUIT + DRY + DISPOSABLES:
                    if have[n] < use[n] * D(busy) * D("0.6"):
                        stock_in(n, round_up(n, use[n] * D(busy) - have[n]), "Local shop")
            if hour in (6, 10, 14, 17):
                make_prep(
                    ist(d, hour, 0), "Tea decoction", D(9000 if hour in (6, 17) else 5000) * D(busy)
                )
                make_prep(ist(d, hour, 1), "Coffee decoction", D(4400) * D(busy))
            if hour == 15 and is_today is False and rnd.random() < 0.9:
                # afternoon shift change on Counter 1
                at = ist(d, 15, 0)
                api.at(at)
                tab = t1
                counted = close_count(expected_cash(api, owner, tab, d))  # syncs: before the append
                tab.shift_ops.append(
                    {
                        "op": "close",
                        "id": uid(),
                        "shift_id": tab.shift,
                        "at": at.isoformat(),
                        "counted_cash_paise": counted,
                        "cashier_id": tab.who["id"],
                    }
                )
                tab.sync(tab.who)
                tab.shift = uid()
                tab.who = evening
                tab.shift_ops.append(
                    {
                        "op": "open",
                        "id": tab.shift,
                        "at": (at + timedelta(minutes=2)).isoformat(),
                        "opening_float_paise": 50000,
                        "cashier_id": evening["id"],
                    }
                )
            n = int(HOURLY[hour] * busy * rnd.uniform(0.8, 1.2))
            for _ in range(n):
                at = ist(d, hour, rnd.randrange(60)) + timedelta(seconds=rnd.randrange(60))
                tab = t2 if (open_c2 and hour >= 8 and rnd.random() < 0.4) else t1
                mode, parts = payment()
                customer, discount, reason = None, 0, ""
                if rnd.random() < 0.015:
                    c = rnd.choice(customers)
                    mode, parts, customer = "credit", None, c
                items = pick_items(hour)
                if rnd.random() < 0.03:
                    discount, reason = 500, rnd.choice(["Regular customer", "Staff", "Offer"])
                b = tab.bill(
                    items,
                    at,
                    tab.who,
                    mode=mode,
                    parts=parts,
                    customer=customer,
                    discount=discount,
                    reason=reason,
                )
                if b["totals"]["total"] < 100:
                    tab.outbox.pop()
                    continue
                if customer:
                    owed[customer["id"]] += b["totals"]["total"]
                elif rnd.random() < 0.05 and mode == "cash":
                    b["customer"] = rnd.choice(customers)  # a known face, paid in cash
            # Table service: a few dine-in and takeaway orders an hour at lunch and evening
            if hour in (8, 9, 12, 13, 16, 17, 18, 19):
                for _ in range(rnd.choice([1, 1, 2, 2, 3])):
                    run_order(
                        tw,
                        t1,
                        ist(d, hour, rnd.randrange(40)),
                        arun,
                        rnd.choice(list(tables.values())),
                        takeaway=rnd.random() < 0.3,
                    )
            # Pay outs during the day
            if hour == 11 and rnd.random() < 0.6:
                amt = rnd.choice([20000, 30000, 45000])
                t1.shift_ops.append(
                    {
                        "op": "cash",
                        "id": uid(),
                        "shift_id": t1.shift,
                        "at": ist(d, 11, 10).isoformat(),
                        "kind": "pay_out",
                        "amount_paise": amt,
                        "reason": rnd.choice(
                            [
                                "Ice block",
                                "Gas cylinder deposit",
                                "Cleaning supplies",
                                "Milk top-up",
                            ]
                        ),
                        "cashier_id": t1.who["id"],
                    }
                )
            if hour == 18 and rnd.random() < 0.3:
                t1.shift_ops.append(
                    {
                        "op": "cash",
                        "id": uid(),
                        "shift_id": t1.shift,
                        "at": ist(d, 18, 5).isoformat(),
                        "kind": "pay_in",
                        "amount_paise": 20000,
                        "reason": "Change from the bank",
                        "cashier_id": t1.who["id"],
                    }
                )
            # Each tablet sends every half hour or so
            api.at(ist(d, hour, 59))
            for tab in (t1, t2, tw):
                tab.sync(getattr(tab, "who", owner) or owner)

        # Khata repayments now and then
        if not is_today and rnd.random() < 0.35:
            payers = [c for c in customers if owed[c["id"]] > 0]
            if payers:
                c = rnd.choice(payers)
                amt = min(owed[c["id"]], rnd.choice([5000, 10000, 20000]))
                api.at(ist(d, 18, 30))
                srv = next(
                    x
                    for x in api.get(f"/customers?q={c['phone']}", owner)["customers"]
                    if x["phone"] == c["phone"]
                )
                api.post(
                    f"/customers/{srv['id']}/repayments",
                    owner,
                    {
                        "id": uid(),
                        "amount_paise": amt,
                        "mode": rnd.choice(["cash", "upi"]),
                        "shift_id": t1.shift,
                    },
                )
                owed[c["id"]] -= amt

        # A void every other day or so (owner, next morning before close)
        if not is_today and rnd.random() < 0.5:
            api.at(ist(d, 20, 30))
            bill_id = rnd.choice(recent_bills(d))
            api.post(
                f"/bills/{bill_id}/void",
                owner,
                {
                    "reason": rnd.choice(
                        ["wrong_item", "duplicate", "payment_failed", "customer_cancelled"]
                    ),
                    "note": rnd.choice(
                        ["Tapped twice", "UPI failed, customer left", "Wrong juice", ""]
                    ),
                },
            )

        # Wastage
        if not is_today:
            api.at(ist(d, 21, 30))
            if rnd.random() < 0.5:
                api.post(
                    "/wastage",
                    ravi,
                    {
                        "ingredient_id": ids["Milk"]["id"],
                        "qty": str(rnd.choice([250, 500, 1000])),
                        "reason": "spoiled",
                        "note": "Curdled",
                    },
                )
            api.post(
                "/wastage",
                ravi,
                {
                    "ingredient_id": ids["Tea decoction"]["id"],
                    "qty": str(rnd.choice([300, 500, 800])),
                    "reason": "prep_loss",
                    "note": "Leftover at close",
                },
            )
            if rnd.random() < 0.4:
                api.post(
                    "/wastage",
                    ravi,
                    {
                        "menu_item_id": t1.menu["Masala tea"]["id"],
                        "qty": "2",
                        "reason": "staff",
                        "note": "Staff tea",
                    },
                )

        if is_today:
            # Right now: tables eating, one with its bill printed, takeaways waiting
            now = datetime.now(UTC).replace(second=0, microsecond=0)
            free = list(tables.values())
            rnd.shuffle(free)
            for mins, stage, takeaway in (
                (55, "billed", False),
                (35, "eating", False),
                (25, "eating", False),
                (15, "waiting", False),
                (12, "waiting", True),
                (6, "waiting", True),
            ):
                run_order(
                    tw,
                    t1,
                    now - timedelta(minutes=mins),
                    arun,
                    free.pop(),
                    takeaway=takeaway,
                    stage=stage,
                )
            api.at(now)
            for tab in (t1, t2, tw):
                tab.sync(getattr(tab, "who", None) or owner)
            break

        # Close drawers at 22:00
        api.at(ist(d, 22, 0))
        for tab in (t1, t2):
            if tab.shift:
                counted = close_count(expected_cash(api, owner, tab, d))  # syncs: before the append
                tab.shift_ops.append(
                    {
                        "op": "close",
                        "id": uid(),
                        "shift_id": tab.shift,
                        "at": ist(d, 22, 0).isoformat(),
                        "counted_cash_paise": counted,
                        "cashier_id": tab.who["id"],
                    }
                )
                tab.sync(tab.who)
                tab.shift = None

        # Day-end count at 22:15 by the closing cashier; the owner approves next morning
        api.at(ist(d, 22, 15))
        have = on_hand()
        lines = []
        for name in COUNTED:
            sys_q = have[name]
            if sys_q <= 0:
                continue
            drift = (
                D(rnd.uniform(-0.035, 0.01))
                if rnd.random() < 0.85
                else D(rnd.uniform(-0.12, -0.04))
            )
            q = (sys_q * (1 + drift)).quantize(D("1"))
            lines.append({"ingredient_id": ids[name]["id"], "loose_qty": str(max(q, D(0)))})
        r = api.post(f"/day-counts/{d.isoformat()}/counts", evening, {"lines": lines})
        if r["recount"]:
            again = [ln for ln in lines if ln["ingredient_id"] in r["recount"]]
            api.post(f"/day-counts/{d.isoformat()}/counts", evening, {"lines": again})
        if d < today - timedelta(days=1):  # yesterday is left for the owner to approve
            api.at(ist(d + timedelta(days=1), 5, 0))
            api.post(f"/day-counts/{d.isoformat()}/approve", owner)

    # An order still open for the owner to see on Purchases
    api.at(datetime.now(UTC) - timedelta(hours=1))
    po("Lakshmi Tea Traders", [("Tea powder", 2000), ("Sugar", 10000)], note="Call before 11")
    for tab in (t1, t2, tw):
        tab.sync(owner)


FRUIT = ["Oranges", "Watermelon", "Pineapple", "Lemon", "Mint leaves", "Ginger"]
DRY = [
    "Tea powder",
    "Coffee powder",
    "Sugar",
    "Cardamom",
    "Badam mix",
    "Malt drink powder",
    "Rose syrup",
    "Mango pulp",
]
DISPOSABLES = [
    "Paper cup",
    "Juice cup with lid",
    "Soda",
    "Water bottle",
    "Butter",
    "Osmania biscuit",
]
# Typical use per day (base units), until the shop has a few days of its own
USE = {
    "Milk": 27000,
    "Tea powder": 540,
    "Coffee powder": 200,
    "Sugar": 2600,
    "Ginger": 270,
    "Cardamom": 12,
    "Lemon": 37,
    "Mint leaves": 70,
    "Oranges": 12000,
    "Watermelon": 9300,
    "Pineapple": 5200,
    "Mango pulp": 1150,
    "Rose syrup": 450,
    "Badam mix": 135,
    "Malt drink powder": 175,
    "Soda": 19,
    "Paper cup": 270,
    "Juice cup with lid": 110,
    "Samosa": 45,
    "Veg puff": 25,
    "Bun": 13,
    "Butter": 140,
    "Osmania biscuit": 27,
    "Water bottle": 8,
}
PACK = {
    "Milk": 500,
    "Tea powder": 250,
    "Coffee powder": 500,
    "Sugar": 1000,
    "Cardamom": 50,
    "Mango pulp": 850,
    "Rose syrup": 750,
    "Badam mix": 500,
    "Malt drink powder": 500,
    "Soda": 24,
    "Paper cup": 50,
    "Juice cup with lid": 50,
    "Bun": 6,
    "Butter": 500,
    "Osmania biscuit": 50,
    "Water bottle": 24,
    "Oranges": 1000,
    "Watermelon": 1000,
    "Pineapple": 1000,
    "Ginger": 250,
    "Mint leaves": 100,
}


def round_up(name: str, qty: D) -> D:
    """Whole packs (or kilos of fruit), as things are bought."""
    if qty <= 0:
        return D(0)
    step = D(PACK.get(name, 1))
    return (qty / step).to_integral_value(rounding="ROUND_CEILING") * step


def daily_use(d: date) -> dict[str, D]:
    """What each item used per day over the last three days (sales, batches, waste)."""
    from app.models import Ingredient, StockLedger  # local: keep the module light

    db = mark_system(SessionLocal())
    rows = dict(
        db.execute(
            select(Ingredient.name, func.sum(StockLedger.qty_delta))
            .join(Ingredient, Ingredient.id == StockLedger.ingredient_id)
            .where(
                StockLedger.qty_delta < 0,
                StockLedger.business_date >= d - timedelta(days=3),
                StockLedger.business_date < d,
                StockLedger.reason != "count_adjustment",
            )
            .group_by(Ingredient.name)
        ).all()
    )
    db.close()
    return {n: max(D(u), -D(rows[n]) / 3) if n in rows else D(u) for n, u in USE.items()}


COUNTED = [
    "Milk",
    "Tea powder",
    "Coffee powder",
    "Sugar",
    "Oranges",
    "Watermelon",
    "Pineapple",
    "Samosa",
    "Veg puff",
    "Paper cup",
    "Juice cup with lid",
    "Tea decoction",
    "Coffee decoction",
]


def expected_cash(api: Api, owner: dict, tab: "Tablet", d: date) -> int:
    """What the drawer should hold, as the owner's report works it out."""
    tab.sync(tab.who)
    rows = api.get(f"/shifts?business_date={d.isoformat()}", owner)["shifts"]
    return next(r["expected_cash_paise"] for r in rows if r["id"] == tab.shift)


def close_count(expected: int) -> int:
    r = rnd.random()
    if r < 0.78:
        return expected
    if r < 0.93:
        return expected - rnd.choice([1000, 2000, 5000])
    return expected + rnd.choice([1000, 2000])


def recent_bills(d: date) -> list[str]:
    db = mark_system(SessionLocal())
    ids = [
        str(x)
        for x in db.scalars(select(Bill.id).where(Bill.business_date == d, Bill.order_id.is_(None)))
    ]
    db.close()
    return ids


def run_order(
    tw: Tablet,
    counter: Tablet,
    start: datetime,
    waiter: dict,
    table: dict,
    *,
    takeaway: bool,
    stage: str = "settled",
):
    """One table or takeaway order, from the waiter's phone to the counter's invoice.
    stage: settled | billed (bill printed, not paid) | eating (all served) | waiting (kitchen)."""
    oid = uid()
    if takeaway:
        tw.event(
            oid,
            "open",
            start,
            waiter,
            {"order_type": "takeaway", "customer_name": rnd.choice(TAKEAWAY_NAMES)},
        )
    else:
        tw.event(
            oid,
            "open",
            start,
            waiter,
            {"order_type": "dine_in", "table_id": table["id"], "covers": rnd.randint(1, 4)},
        )
    hour = start.astimezone(IST).hour
    lines = []
    for r_no in range(1 if stage == "waiting" else rnd.choice([1, 1, 2])):
        at = start + timedelta(minutes=1 + r_no * 12)
        tw.kot += 1
        new = [
            tw.kot_line(n, q, m, rnd.choice(["", "", "", "less sweet", "hot"]))
            for n, q, m in pick_items(hour)
        ]
        tw.event(oid, "kot", at, waiter, {"kot_no": f"{tw.device['code']}-{tw.kot}", "lines": new})
        lines += new
        if stage != "waiting":
            tw.event(
                oid,
                "ready",
                at + timedelta(minutes=5),
                waiter,
                {"line_ids": [x["line_id"] for x in new]},
            )
    if stage in ("eating", "waiting"):
        return oid
    end = start + timedelta(minutes=rnd.randint(25, 45))
    if not takeaway:
        tw.event(oid, "bill_printed", end - timedelta(minutes=4), waiter)
    if stage == "billed":
        return oid
    mode, parts = payment()
    items = [(x["name"], x["qty"], [m["name"] for m in x["modifiers"]]) for x in lines]
    b = counter.bill(
        items, end, getattr(counter, "who", waiter), mode=mode, parts=parts, order_id=oid
    )
    tw.event(oid, "settle", end, waiter, {"bill_id": b["id"]})
    return oid


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    keep_path = os.environ.get("DEMO_KEEP")
    if not keep_path:
        sys.exit("Set DEMO_KEEP to a keep.json (see the docstring)")
    keep = json.loads(Path(keep_path).read_text())
    db = mark_system(SessionLocal())
    if db.scalar(select(func.count()).select_from(Shop)):
        sys.exit("The database already has a shop: demo data goes into an EMPTY database")
    db.close()
    shop, people = make_shop(keep)
    api = Api(uuid.UUID(shop["id"]))
    owner = people["owner"][0]
    api.at(ist(datetime.now(IST).date() - timedelta(days=DAYS + 1), 9))
    ids = build_catalogue(api, owner)
    tables = build_floor(api, owner)
    simulate(api, people, ids, tables)
    db = mark_system(SessionLocal())
    n = db.scalar(select(func.count()).select_from(Bill))
    db.close()
    print(f"Demo data: {n} bills over {DAYS} days for shop {shop['id']}")


if __name__ == "__main__":
    main()

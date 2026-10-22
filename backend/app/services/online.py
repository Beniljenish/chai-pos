"""Food courts and online orders (README, "9.11").

Two kinds of caller meet here and they must never be confused:

* An OWNER managing their own shop's place in a food court. They are
  authenticated, and every function takes the shop id from their token.
* A CUSTOMER with no login, scanning the QR. They can read an outlet's menu
  and place an order, and nothing else. Everything a customer reads or writes
  goes through a session bound to ONE outlet's shop (`shop_session`), picked by
  the outlet row the food court names, never by anything the customer sends.

A customer's order is an ordinary takeaway Order, written as the same events a
till would write (open, kot), by a stand-in "Online ordering" device and user so
the kitchen screen, ready messages, billing and receipts all work unchanged.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.security import hash_password
from app.core.time import business_date, utcnow
from app.db.session import SessionLocal
from app.db.tenancy import bind_tenant, mark_system
from app.models import (
    Device,
    FoodCourt,
    FoodCourtOutlet,
    MenuItem,
    MenuItemModifier,
    Modifier,
    OnlineOrder,
    Order,
    OrderEvent,
    OrderEventKind,
    OrderStatus,
    OrderType,
    Role,
    Shop,
    User,
)
from app.services import gst, payments
from app.services import orders as order_service

ONLINE_USER_NAME = "Online ordering"  # the stand-in author of customers' orders
ONLINE_DEVICE_CODE = "ON"
MAX_QTY = 20
MAX_LINES = 15
MAX_TOTAL_QTY = 40
PHONE_ORDERS_PER_HOUR = 5
OUTLET_OPEN_ORDERS = 40


class OnlineError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.extra = code, message, status, extra or {}


@contextmanager
def shop_session(shop_id: uuid.UUID):
    """A session that can see exactly one shop, for work done on a customer's behalf."""
    with SessionLocal() as db:
        yield bind_tenant(db, shop_id)


def system_session() -> Session:
    return mark_system(SessionLocal())


# ---------------------------------------------------------------- owner: their place in a court
def my_outlet(db: Session, shop_id: uuid.UUID) -> FoodCourtOutlet | None:
    return db.scalar(select(FoodCourtOutlet).where(FoodCourtOutlet.shop_id == shop_id))


def view(db: Session, shop_id: uuid.UUID) -> dict:
    """The food court this shop is in, as its owner sees it. The owner does not make,
    join or leave courts: the super admin does (services/platform.py)."""
    mine = my_outlet(db, shop_id)
    if mine is None:
        return {"court": None}
    court = db.get(FoodCourt, mine.court_id)
    rows = db.execute(
        select(FoodCourtOutlet, Shop.name)
        .join(Shop, Shop.id == FoodCourtOutlet.shop_id)
        .where(FoodCourtOutlet.court_id == court.id)
        .order_by(FoodCourtOutlet.joined_at)
    ).all()
    return {
        "court": {"id": court.id, "name": court.name, "slug": court.slug},
        "accepting_orders": mine.accepting_orders,
        "prep_minutes": mine.prep_minutes,
        "fee_bp": mine.fee_bp,
        "pickup_enabled": mine.pickup_enabled,
        "pickup_capacity": mine.pickup_capacity,
        "outlets": [
            {
                "id": o.id,
                "name": name,
                "accepting_orders": o.accepting_orders,
                "is_me": o.shop_id == shop_id,
            }
            for o, name in rows
        ],
    }


def set_pickup(db: Session, shop_id: uuid.UUID, enabled: bool | None, capacity: int | None) -> None:
    mine = my_outlet(db, shop_id)
    if mine is None:
        raise OnlineError("not_in_a_court", "This shop is not in a food court", 404)
    if enabled is not None:
        mine.pickup_enabled = enabled
    if capacity is not None:
        mine.pickup_capacity = capacity
    db.commit()


def set_accepting(db: Session, shop_id: uuid.UUID, on: bool) -> None:
    mine = my_outlet(db, shop_id)
    if mine is None:
        raise OnlineError("not_in_a_court", "This shop is not in a food court", 404)
    mine.accepting_orders = on
    db.commit()


# ---------------------------------------------------------------- customer: read
def _court(sysdb: Session, slug: str) -> FoodCourt:
    court = sysdb.scalar(select(FoodCourt).where(FoodCourt.slug == slug))
    if court is None:
        raise OnlineError("not_found", "No such food court", 404)
    return court


def _outlet(sysdb: Session, court: FoodCourt, outlet_id: uuid.UUID) -> FoodCourtOutlet:
    outlet = sysdb.get(FoodCourtOutlet, outlet_id)
    if outlet is None or outlet.court_id != court.id:
        raise OnlineError("not_found", "No such outlet", 404)
    return outlet


def public_court(sysdb: Session, slug: str) -> dict:
    court = _court(sysdb, slug)
    rows = sysdb.execute(
        select(FoodCourtOutlet, Shop.name)
        .join(Shop, Shop.id == FoodCourtOutlet.shop_id)
        .where(FoodCourtOutlet.court_id == court.id)
        .order_by(Shop.name)
    ).all()
    return {
        "name": court.name,
        "location": court.location,
        # Whether the customer may be offered "pay online" (the Razorpay keys are set).
        "online_payment": payments.online_enabled(),
        "outlets": [
            {"id": o.id, "name": name, "open": o.accepting_orders, "prep_minutes": o.prep_minutes}
            for o, name in rows
        ],
    }


def public_courts(sysdb: Session) -> list[dict]:
    """Every food court that has at least one outlet, for a signed-in customer to pick
    from. Names and counts only: the outlets themselves come from public_court."""
    courts = []
    for court in sysdb.scalars(select(FoodCourt).order_by(FoodCourt.name)):
        flags = sysdb.scalars(
            select(FoodCourtOutlet.accepting_orders).where(FoodCourtOutlet.court_id == court.id)
        ).all()
        if flags:
            courts.append(
                {
                    "name": court.name,
                    "slug": court.slug,
                    "location": court.location,
                    "outlets": len(flags),
                    "open": sum(1 for f in flags if f),
                }
            )
    return courts


def public_menu(sysdb: Session, slug: str, outlet_id: uuid.UUID) -> dict:
    court = _court(sysdb, slug)
    outlet = _outlet(sysdb, court, outlet_id)
    with shop_session(outlet.shop_id) as db:
        shop = db.scalar(select(Shop))
        items = db.scalars(
            select(MenuItem).where(MenuItem.is_active).order_by(MenuItem.category, MenuItem.name)
        ).all()
        # The options each dish offers, as the till offers them (switched-off ones left out).
        options: dict[uuid.UUID, list[dict]] = {}
        for link, mod in db.execute(
            select(MenuItemModifier, Modifier)
            .join(Modifier, Modifier.id == MenuItemModifier.modifier_id)
            .where(Modifier.is_active)
            .order_by(Modifier.name)
        ):
            options.setdefault(link.menu_item_id, []).append(
                {
                    "id": mod.id,
                    "name": mod.name,
                    "price_delta_paise": mod.price_delta_paise,
                    # a size changes the quantity made (Large); anything else is a tick box
                    "is_size": mod.scale_factor != 1,
                }
            )
        # Only what a customer needs to choose and to see the price they will pay.
        return {
            "outlet": shop.name,
            "open": outlet.accepting_orders,
            "prep_minutes": outlet.prep_minutes,
            "gst_type": shop.gst_type.value,
            "items": [
                {
                    "id": i.id,
                    "name": i.name,
                    "category": i.category,
                    "price_paise": i.price_paise,
                    "gst_rate_bp": i.gst_rate_bp,
                    "tax_inclusive": i.tax_inclusive,
                    "sold_out": i.is_sold_out,
                    "description": i.description,
                    "name_ta": i.name_ta,
                    "description_ta": i.description_ta,
                    "photo_url": i.photo_url,
                    "is_veg": i.is_veg,
                    "options": options.get(i.id, []),
                }
                for i in items
            ],
        }


# ---------------------------------------------------------------- customer: order
@dataclass(frozen=True)
class Pick:
    """One dish a customer chose, with the options (modifiers) they ticked."""

    item_id: uuid.UUID
    qty: int
    mods: tuple[uuid.UUID, ...] = ()


@dataclass
class OrderInput:
    request_id: uuid.UUID
    customer_id: uuid.UUID  # the signed-in account; name and phone come from it
    name: str
    phone: str
    note: str
    message_ok: bool
    items: list[Pick]
    # (online payment id, paise paid for this outlet's order) when it was paid online.
    paid: tuple[uuid.UUID, int] | None = None


def _clean_text(s: str, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", s).strip()[:limit]


def _prefix(shop_name: str) -> str:
    letters = [w[0] for w in re.findall(r"[A-Za-z]+", shop_name)]
    return ("".join(letters[:2]) or "O").upper()


def status_key(shop_id: uuid.UUID, order_id: uuid.UUID) -> str:
    key = get_settings().jwt_secret.encode()
    sig = hmac.new(key, b"online:" + shop_id.bytes + order_id.bytes, hashlib.sha256)
    return shop_id.hex + order_id.hex + sig.hexdigest()[:32]


def _parse_key(key: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    if not re.fullmatch(r"[0-9a-f]{96}", key or ""):
        return None
    shop_id, order_id = uuid.UUID(key[:32]), uuid.UUID(key[32:64])
    ok = hmac.compare_digest(status_key(shop_id, order_id), key)
    return (shop_id, order_id) if ok else None


def _actor(db: Session) -> tuple[Device, User]:
    """The stand-in device and user that author customers' orders, made on first use."""
    device = db.scalar(select(Device).where(Device.code == ONLINE_DEVICE_CODE))
    if device is None:
        device = Device(name="Online orders", code=ONLINE_DEVICE_CODE)
        db.add(device)
    user = db.scalar(select(User).where(User.name == ONLINE_USER_NAME))
    if user is None:
        user = User(
            name=ONLINE_USER_NAME,
            phone="0" + "".join(secrets.choice("0123456789") for _ in range(9)),  # can never log in
            role=Role.cashier,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_active=False,
            must_change_password=True,
        )
        db.add(user)
    db.flush()
    return device, user


def _total(lines: list[dict], gst_type) -> int:
    live = [ln for ln in lines if ln["qty"] > 0]
    if not live:
        return 0
    return gst.compute_bill(
        [
            gst.LineIn(
                unit_price_paise=ln["unit_price_paise"],
                qty=ln["qty"],
                gst_rate_bp=ln["gst_rate_bp"],
                tax_inclusive=ln["tax_inclusive"],
                modifier_deltas_paise=tuple(
                    int(m["price_delta_paise"]) for m in ln.get("modifiers") or []
                ),
            )
            for ln in live
        ],
        gst_type,
    ).total


# A line is a dish plus its set of options: 2 teas, and 1 Large tea, are two lines.
LineKey = tuple[uuid.UUID, tuple[uuid.UUID, ...]]


def _wanted(picks: list[Pick]) -> dict[LineKey, int]:
    wanted: dict[LineKey, int] = {}
    for p in picks:
        key = (p.item_id, tuple(sorted(set(p.mods), key=str)))
        wanted[key] = wanted.get(key, 0) + p.qty
    if not wanted:
        raise OnlineError("empty_order", "Choose at least one dish")
    if (
        len(wanted) > MAX_LINES
        or sum(wanted.values()) > MAX_TOTAL_QTY
        or max(wanted.values()) > MAX_QTY
    ):
        raise OnlineError("order_too_big", "That is a lot for one order. Split it into two.")
    return wanted


def _load_menu(db: Session, wanted: dict[LineKey, int]) -> dict[uuid.UUID, MenuItem]:
    """The dishes asked for, from the outlet's own menu (the session sees one shop only);
    refuses any that are gone or sold out."""
    item_ids = {item_id for item_id, _ in wanted}
    menu = {
        m.id: m
        for m in db.scalars(
            select(MenuItem).where(MenuItem.id.in_(list(item_ids)), MenuItem.is_active)
        )
    }
    if any(i not in menu for i in item_ids):
        raise OnlineError("items_unavailable", "Some dishes are no longer on the menu", 409)
    sold_out = [menu[i].name for i in item_ids if menu[i].is_sold_out]
    if sold_out:
        raise OnlineError(
            "items_unavailable", "Sold out: " + ", ".join(sold_out), 409, {"names": sold_out}
        )
    return menu


def _load_mods(db: Session, wanted: dict[LineKey, int]) -> dict[LineKey, list[dict]]:
    """The options for each line, built here from the outlet's own definitions and saved on the
    order exactly as the till saves them (name, price change, size factor, stock change). Nothing
    about an option's price or stock effect is taken from the phone, and an option the dish does
    not offer, or one switched off, is refused."""
    ids = {mid for _, mods in wanted for mid in mods}
    if not ids:
        return {key: [] for key in wanted}
    rows = {
        m.id: m
        for m in db.scalars(
            select(Modifier)
            .where(Modifier.id.in_(ids), Modifier.is_active)
            .options(selectinload(Modifier.lines))
        )
    }
    allowed = {
        (r.menu_item_id, r.modifier_id)
        for r in db.scalars(
            select(MenuItemModifier).where(
                MenuItemModifier.menu_item_id.in_({i for i, _ in wanted}),
                MenuItemModifier.modifier_id.in_(ids),
            )
        )
    }
    out: dict[LineKey, list[dict]] = {}
    for key in wanted:
        item_id, mods = key
        snaps = []
        for mid in mods:
            if rows.get(mid) is None or (item_id, mid) not in allowed:
                raise OnlineError("items_unavailable", "An option is no longer available", 409)
        for mid in sorted(mods, key=lambda i: rows[i].name):  # a steady order: "Large, Less sugar"
            mod = rows[mid]
            snaps.append(
                {
                    "modifier_id": str(mod.id),
                    "name": mod.name,
                    "price_delta_paise": mod.price_delta_paise,
                    "scale_factor": str(mod.scale_factor),
                    "lines": [
                        {"ingredient_id": str(ln.ingredient_id), "qty_delta": str(ln.qty_delta)}
                        for ln in mod.lines
                    ],
                }
            )
        if sum(1 for sn in snaps if Decimal(sn["scale_factor"]) != 1) > 1:
            raise OnlineError("bad_options", "Choose one size", 422)
        out[key] = snaps
    return out


def _cart_lines(
    menu: dict[uuid.UUID, MenuItem],
    wanted: dict[LineKey, int],
    snaps: dict[LineKey, list[dict]],
    *,
    ids: bool = False,
) -> list[dict]:
    out = []
    for key, qty in wanted.items():
        m = menu[key[0]]
        line = {
            "menu_item_id": str(m.id),
            "name": m.name,
            "qty": qty,
            "unit_price_paise": m.price_paise,
            "gst_rate_bp": m.gst_rate_bp,
            "tax_inclusive": m.tax_inclusive,
            "modifiers": snaps[key],
            "note": "",
        }
        if ids:
            line["line_id"] = str(uuid.uuid4())
        out.append(line)
    return out


def line_label(line: dict) -> str:
    """ "Masala tea (Large, Less sugar)": what the customer and the outlet read."""
    mods = [m["name"] for m in line.get("modifiers") or []]
    return f"{line['name']} ({', '.join(mods)})" if mods else line["name"]


def quote(sysdb: Session, slug: str, outlet_id: uuid.UUID, items: list[Pick]) -> tuple[str, int]:
    """What an order would cost at this outlet right now, with the same checks as placing
    it (open, dishes on the menu and not sold out, options offered, size limits) and nothing
    written. Returns (outlet name, total in paise)."""
    court = _court(sysdb, slug)
    outlet = _outlet(sysdb, court, outlet_id)
    if not outlet.accepting_orders:
        raise OnlineError("outlet_closed", "This outlet is not taking orders right now", 409)
    wanted = _wanted(items)
    with shop_session(outlet.shop_id) as db:
        shop = db.scalar(select(Shop))
        menu = _load_menu(db, wanted)
        lines = _cart_lines(menu, wanted, _load_mods(db, wanted))
        return shop.name, _total(lines, shop.gst_type)


def place_order(sysdb: Session, slug: str, outlet_id: uuid.UUID, body: OrderInput) -> dict:
    court = _court(sysdb, slug)
    outlet = _outlet(sysdb, court, outlet_id)
    if not outlet.accepting_orders:
        raise OnlineError("outlet_closed", "This outlet is not taking orders right now", 409)

    wanted = _wanted(body.items)

    with shop_session(outlet.shop_id) as db:
        existing = db.scalar(select(Order).where(Order.id == body.request_id))
        if existing is not None:  # the same tap sent twice: the same order, once
            return _placed(db, existing, outlet.shop_id, body.customer_id)

        shop = db.scalar(select(Shop))
        menu = _load_menu(db, wanted)
        snaps = _load_mods(db, wanted)

        now = utcnow()
        hour_ago = now - timedelta(hours=1)
        same_phone = db.scalar(
            select(func.count())
            .select_from(Order)
            .join(OnlineOrder, OnlineOrder.order_id == Order.id)
            .where(Order.state["customer_phone"].astext == body.phone, Order.opened_at > hour_ago)
        )
        # A paid order is not a flood: real money is a stronger brake than a counter.
        if body.paid is None and (same_phone or 0) >= PHONE_ORDERS_PER_HOUR:
            raise OnlineError(
                "too_many_orders", "Too many orders from this number. Try later.", 429
            )
        waiting = db.scalar(
            select(func.count())
            .select_from(Order)
            .join(OnlineOrder, OnlineOrder.order_id == Order.id)
            .where(Order.status == OrderStatus.open)
        )
        if (waiting or 0) >= OUTLET_OPEN_ORDERS:
            raise OnlineError("outlet_busy", "This outlet is very busy. Try again shortly.", 429)

        device, user = _actor(db)
        today = business_date(now)
        count = (
            db.scalar(
                select(func.count())
                .select_from(OnlineOrder)
                .where(OnlineOrder.business_date == today)
            )
            or 0
        )
        prefix = _prefix(shop.name)
        token = ""
        for attempt in range(1, 8):
            token = f"{prefix}-{count + attempt}"
            taken = db.scalar(
                select(OnlineOrder.id).where(
                    OnlineOrder.business_date == today, OnlineOrder.token == token
                )
            )
            if taken is None:
                break
        else:
            raise OnlineError("busy", "Please try again", 503)

        order = Order(
            id=body.request_id,
            device_id=device.id,
            order_type=OrderType.takeaway,
            status=OrderStatus.open,
            table_id=None,
            opened_by=user.id,
            opened_at=now,
            business_date=today,
            state=order_service.empty_state(),
        )
        db.add(order)
        db.flush()
        lines = _cart_lines(menu, wanted, snaps, ids=True)
        if body.paid is not None and _total(lines, shop.gst_type) != body.paid[1]:
            # The prices moved between paying and placing: do not serve what was not paid for.
            raise OnlineError("price_changed", "Prices changed while you were paying", 409)
        name = _clean_text(body.name, 40)
        events = [
            (
                OrderEventKind.open,
                now,
                {
                    "order_type": "takeaway",
                    # The token leads the name, so the kitchen and the counter read "JT-17 Ravi".
                    "customer_name": f"{token} {name}",
                    "customer_phone": body.phone,
                    "message_ok": body.message_ok,
                    "note": _clean_text(body.note, 120),
                    "source": "online",
                    **({"paid_online_paise": body.paid[1]} if body.paid is not None else {}),
                },
            ),
            (
                OrderEventKind.kot,
                now + timedelta(milliseconds=1),
                {"kot_no": token, "lines": lines},
            ),
        ]
        for kind, at, data in events:
            ev = {
                "id": uuid.uuid4(),
                "order_id": order.id,
                "kind": kind.value,
                "at": at,
                "data": data,
            }
            db.add(
                OrderEvent(
                    id=ev["id"],
                    order_id=order.id,
                    kind=kind,
                    data=data,
                    by=user.id,
                    device_id=device.id,
                    at=at,
                    content_hash=order_service._hash(ev),
                )
            )
        db.add(
            OnlineOrder(
                order_id=order.id,
                court_id=court.id,
                token=token,
                business_date=today,
                customer_id=body.customer_id,
                payment_id=body.paid[0] if body.paid is not None else None,
                paid_paise=body.paid[1] if body.paid is not None else None,
            )
        )
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise OnlineError("busy", "Please try again", 503) from None
        order_service.recompute(db, order.id)
        db.commit()
        return _placed(db, order, outlet.shop_id, body.customer_id)


def _placed(db: Session, order: Order, shop_id: uuid.UUID, customer_id: uuid.UUID) -> dict:
    online = db.scalar(select(OnlineOrder).where(OnlineOrder.order_id == order.id))
    # Not an online order, or somebody else's: reusing an id must never reveal it.
    if online is None or online.customer_id != customer_id:
        raise OnlineError("not_found", "No such order", 404)
    return {
        "order_id": order.id,
        "token": online.token,
        "status_key": status_key(shop_id, order.id),
    }


# ---------------------------------------------------------------- customer: status
def public_state(state: dict) -> str:
    if state["status"] == "cancelled":
        return "declined"
    if state["status"] == "settled":
        return "collected"
    lines = [ln for ln in state["lines"] if ln["qty"] > 0]
    return "ready" if lines and all(ln.get("ready") for ln in lines) else "received"


def public_order(key: str) -> dict:
    parsed = _parse_key(key)
    if parsed is None:
        raise OnlineError("not_found", "No such order", 404)
    shop_id, order_id = parsed
    with shop_session(shop_id) as db:
        order = db.scalar(select(Order).where(Order.id == order_id))
        online = db.scalar(select(OnlineOrder).where(OnlineOrder.order_id == order_id))
        if order is None or online is None:
            raise OnlineError("not_found", "No such order", 404)
        shop = db.scalar(select(Shop))
        lines = order.state["lines"]
        return {
            "token": online.token,
            "outlet": shop.name,
            "status": public_state(order.state),
            "items": [{"name": line_label(ln), "qty": ln["qty"]} for ln in lines if ln["qty"] > 0],
            "total_paise": _total(lines, shop.gst_type),
            # Paid in the app (README, "9.14"): the page says "Paid", not "Pay at the counter".
            "paid_online": online.payment_id is not None,
        }

"""Customer messages (README, "Phase 8b"): the owner's outbox, and the public
receipt page that a receipt message links to."""

from html import escape

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.deps import Caller, require_owner
from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Bill, GstType, Message, Order, Shop
from app.services import messages
from app.services.reports import bill_rows, ist_time

router = APIRouter(tags=["messages"])


@router.get("/messages")
def outbox(caller: Caller = Depends(require_owner)) -> dict:
    """Owner: the latest messages, with the customer's number masked."""
    rows = caller.db.scalars(select(Message).order_by(Message.created_at.desc()).limit(200)).all()
    orders = {
        o.id: o
        for o in caller.db.scalars(select(Order).where(Order.id.in_({m.order_id for m in rows})))
    }
    return {
        "provider": "inkbox" if messages._transport() is not None else "log",
        "messages": [
            {
                "id": m.id,
                "kind": m.kind,
                "order_id": m.order_id,
                "to": messages.mask((orders[m.order_id].state or {}).get("customer_phone", "")),
                "text": m.text,
                "status": m.status,
                "attempts": m.attempts,
                "last_error": m.last_error,
                "provider_id": m.provider_id,
                "created_at": m.created_at,
                "sent_at": m.sent_at,
            }
            for m in rows
        ],
    }


@router.post("/messages/retry")
def retry(caller: Caller = Depends(require_owner)) -> dict:
    """Owner: try waiting messages now (they are also retried by every sync)."""
    return messages.deliver_pending(caller.db)


TITLES = {
    GstType.regular: "Tax invoice",
    GstType.composition: "Bill of supply",
    GstType.unregistered: "Bill",
}


@router.get("/receipt", response_class=HTMLResponse)
def receipt(t: str = Query(max_length=80)) -> HTMLResponse:
    """The customer's copy of a bill, opened from a message without logging in.
    The token is the bill id plus an HMAC of it, so ids cannot be guessed or walked."""
    bill_id = messages.bill_for_token(t)
    not_found = HTMLResponse("<!doctype html><title>Not found</title>Not found", 404)
    if bill_id is None:
        return not_found
    with SessionLocal() as db:
        mark_system(db)
        bill = db.get(Bill, bill_id)
        if bill is None:
            return not_found
        shop = db.get(Shop, bill.shop_id)
        head = [f"<h1>{escape(shop.name)}</h1>"]
        if shop.address:
            head.append(f"<p>{escape(shop.address)}</p>")
        if shop.gst_type != GstType.unregistered and shop.gstin:
            head.append(f"<p>GSTIN {escape(shop.gstin)}</p>")
        head.append(f"<p><strong>{TITLES[shop.gst_type]}</strong></p>")
        head.append(f"<p>{escape(bill.invoice_no)} · {escape(ist_time(bill.sold_at))}</p>")
        if bill.status.value == "void":
            head.append("<p class=void>VOIDED: not a valid bill</p>")
        rows = "".join(
            f"<tr><td>{escape(a)}</td><td class=r>{escape(b)}</td></tr>" for a, b in bill_rows(bill)
        )
    page = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        f"<title>{escape(shop.name)}: bill {escape(bill.invoice_no)}</title><style>"
        "body{font-family:system-ui,sans-serif;max-width:420px;margin:0 auto;padding:16px;"
        "color:#1d2731}h1{font-size:1.3rem;margin:0}p{margin:4px 0}table{width:100%;"
        "border-collapse:collapse;margin-top:12px}td{padding:6px 0;border-top:1px solid #ddd}"
        ".r{text-align:right}.void{color:#b3261e;font-weight:700}</style></head><body>"
        + "".join(head)
        + f"<table>{rows}</table></body></html>"
    )
    return HTMLResponse(
        page,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
            "frame-ancestors 'none'",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex",
        },
    )

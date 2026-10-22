"""The owner's short end-of-day message (README, "9.17").

A few lines, in the words an owner would type to a partner: sales, bills, the top sellers,
cash vs UPI, and how many things need them. Sent through the same provider as customer
messages; with none configured it is only shown on screen (the owner can read what would go).
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models import Shop
from app.services import alerts, messages, reports

log = logging.getLogger(__name__)


def text_for(db: Session, shop: Shop, d: date) -> str:
    f = reports.daily_figures(db, d)
    rupees = reports.rupees
    lines = [
        f"{shop.name} · {reports.day_label(d)}",
        f"Sales {rupees(f['total'])} from {f['bills']} bill" + ("" if f["bills"] == 1 else "s"),
    ]
    modes = [
        f"{label} {rupees(f['by_mode'][m])}"
        for m, label in (("cash", "Cash"), ("upi", "UPI"), ("card", "Card"))
        if f["by_mode"].get(m)
    ]
    if modes:
        lines.append(" · ".join(modes))
    if f["top"]:
        lines.append("Top: " + ", ".join(f"{n} ×{q}" for n, q, _ in f["top"][:3]))
    if f["wasted"]:
        lines.append(f"Wasted {rupees(f['wasted'])}")
    urgent = [a for a in alerts.build(db, d) if a["urgency"] != "info"]
    if urgent:
        lines.append(f"{len(urgent)} thing{'' if len(urgent) == 1 else 's'} need you: open the app")
    return "\n".join(lines)


def send(db: Session, shop: Shop, d: date) -> str:
    """Send yesterday's message if the owner switched it on. Returns what happened; never raises."""
    if not shop.summary_on or not shop.summary_phone:
        return "off"
    try:
        return messages.send_text(
            shop.summary_phone, text_for(db, shop, d), f"summary:{shop.id}:{d}"
        )
    except Exception:  # noqa: BLE001 - one shop's message must not stop the others
        log.exception("daily summary failed")
        return "failed"

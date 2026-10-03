"""What the owner's emails say. Pure builders: read the database, return
(subject, html, text, attachments). Delivery is app/services/email.py.

All shop-supplied text (item and shop names) is HTML-escaped.
"""

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import (
    Bill,
    BillLine,
    BillStatus,
    DayCount,
    Device,
    EmailKind,
    Ingredient,
    Shop,
    StockLedger,
    User,
    WastageEntry,
)
from app.services import dayend
from app.services.email import b64, enqueue

PAYMENT = {"cash": "Cash", "upi": "UPI", "card": "Card"}
REASON = {
    "spoiled": "Spoiled / expired",
    "spilled": "Spilled / dropped",
    "remake": "Remade",
    "prep_loss": "Leftover thrown away",
    "staff": "Staff drinks",
    "complimentary": "Free",
    "theft": "Theft / unexplained",
}


# ---------------------------------------------------------------- formatting
def rupees(paise: int) -> str:
    """Indian grouping: 1234567 paise -> '₹12,345.67'; whole rupees drop '.00'."""
    sign = "-" if paise < 0 else ""
    p = abs(int(paise))
    whole, frac = divmod(p, 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{sign}₹{s}" + (f".{frac:02d}" if frac else "")


def qty(value: Decimal, unit: str) -> str:
    v = Decimal(value)
    big = {"ml": ("L", 1000), "g": ("kg", 1000)}.get(unit)
    if big and abs(v) >= big[1]:
        return f"{_num(v / big[1])} {big[0]}"
    return f"{_num(v)} {'pcs' if unit == 'piece' else unit}"


def _num(v: Decimal) -> str:
    out = f"{Decimal(v).quantize(Decimal('0.001')):f}".rstrip("0").rstrip(".")
    return out or "0"


def day_label(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html><body style="margin:0;background:#e6eaed;'
        'font-family:Arial,Helvetica,sans-serif;color:#1d2730">'
        '<div style="max-width:560px;margin:0 auto;padding:16px">'
        f'<h1 style="font-size:20px;margin:0 0 12px">{escape(title)}</h1>'
        f'<div style="background:#fff;border-radius:12px;padding:16px">{body}</div>'
        '<p style="font-size:12px;color:#55626d">Sent by Chai POS.</p></div></body></html>'
    )


def _table(rows: list[tuple], head: tuple | None = None, right_from: int = 1) -> str:
    def cell(v, i, tag="td"):
        align = "right" if i >= right_from else "left"
        return f'<{tag} style="padding:4px 6px;text-align:{align}">{escape(str(v))}</{tag}>'

    h = "<tr>" + "".join(cell(v, i, "th") for i, v in enumerate(head)) + "</tr>" if head else ""
    b = "".join("<tr>" + "".join(cell(v, i) for i, v in enumerate(r)) + "</tr>" for r in rows)
    return f'<table style="width:100%;border-collapse:collapse;font-size:14px">{h}{b}</table>'


def _ist_time(dt) -> str:
    tz = ZoneInfo(get_settings().shop_timezone)
    return dt.astimezone(tz).strftime("%d %b %Y, %I:%M %p")


# ---------------------------------------------------------------- one bill
def enqueue_bill(db: Session, shop: Shop, bill: Bill) -> None:
    if not shop.email_each_bill:
        return
    lines = sorted(bill.lines, key=lambda ln: ln.position)
    rows = [(f"{ln.qty} × {ln.name_snapshot}", rupees(ln.total_paise)) for ln in lines]
    if bill.cgst_paise:
        rows += [("CGST", rupees(bill.cgst_paise)), ("SGST", rupees(bill.sgst_paise))]
    rows.append(("Total", rupees(bill.total_paise)))
    pay = PAYMENT.get(bill.payment_mode.value, bill.payment_mode.value)
    subject = f"{rupees(bill.total_paise)} · {bill.invoice_no} · {pay}"
    meta = f"{bill.invoice_no} · {_ist_time(bill.sold_at)} · paid by {pay}"
    html = _page(f"Bill {bill.invoice_no}", f"<p>{escape(meta)}</p>" + _table(rows))
    text = meta + "\n" + "\n".join(f"{a}: {b}" for a, b in rows)
    enqueue(db, shop, EmailKind.bill, f"bill:{bill.id}", subject, html, text)


# ---------------------------------------------------------------- day end
def enqueue_day_end(db: Session, shop: Shop, dc: DayCount) -> None:
    if not shop.email_day_end:
        return
    lines = dayend.report_lines(db, dc)
    missing = -sum(min(r.variance_paise, 0) for r in lines)
    flagged = [r for r in lines if r.flagged]
    wastage = dict(
        db.execute(
            select(WastageEntry.reason, func.sum(WastageEntry.value_paise))
            .where(WastageEntry.business_date == dc.business_date)
            .group_by(WastageEntry.reason)
        ).all()
    )
    subject = f"Day end {day_label(dc.business_date)}: {rupees(missing)} missing" + (
        f", {len(flagged)} to check" if flagged else ""
    )
    rows = []
    for r in lines:
        adh = r.adherence_pct
        rows.append(
            (
                r.ingredient.name + (" ⚑" if r.flagged else ""),
                qty(r.expected, r.ingredient.base_unit),
                qty(r.counted, r.ingredient.base_unit),
                ("+" if r.variance > 0 else "") + qty(r.variance, r.ingredient.base_unit),
                rupees(r.variance_paise) if r.cost else "no price",
                f"{adh}%" if adh is not None else "",
            )
        )
    waste_rows = [(REASON.get(k.value, k.value), rupees(int(v or 0))) for k, v in wastage.items()]
    body = (
        f"<p><b>Missing: {rupees(missing)}</b> · Wasted (recorded): "
        f"{rupees(sum(int(v or 0) for v in wastage.values()))} · "
        f"Outside tolerance: {len(flagged)}</p>"
        + _table(rows, ("Item", "Should be", "Counted", "Gap", "₹", "Adherence"))
        + ("<h3 style='font-size:15px'>Wastage</h3>" + _table(waste_rows) if waste_rows else "")
        + "<p style='font-size:12px;color:#55626d'>⚑ = outside tolerance. Adherence below 100% "
        "means more was used than the recipe says.</p>"
    )
    text = subject + "\n" + "\n".join(" | ".join(map(str, r)) for r in rows)
    enqueue(
        db,
        shop,
        EmailKind.day_end,
        f"day_end:{dc.business_date.isoformat()}",
        subject,
        _page(subject, body),
        text,
    )


# ---------------------------------------------------------------- daily summary
def daily_figures(db: Session, d: date) -> dict:
    every = db.scalars(select(Bill).where(Bill.business_date == d)).all()
    bills = [b for b in every if b.status != BillStatus.void]
    voided = [b for b in every if b.status == BillStatus.void]
    by_mode: dict[str, int] = defaultdict(int)
    for b in bills:
        by_mode[b.payment_mode.value] += b.total_paise
    top = db.execute(
        select(BillLine.name_snapshot, func.sum(BillLine.qty), func.sum(BillLine.total_paise))
        .join(Bill, Bill.id == BillLine.bill_id)
        .where(Bill.business_date == d, Bill.status != BillStatus.void)
        .group_by(BillLine.name_snapshot)
        .order_by(func.sum(BillLine.total_paise).desc())
        .limit(10)
    ).all()
    wasted = db.scalar(
        select(func.coalesce(func.sum(WastageEntry.value_paise), 0)).where(
            WastageEntry.business_date == d
        )
    )
    day = db.scalar(select(DayCount).where(DayCount.business_date == d))
    return {
        "bills": len(bills),
        "total": sum(b.total_paise for b in bills),
        "gst": sum(b.cgst_paise + b.sgst_paise for b in bills),
        "by_mode": dict(by_mode),
        "mismatch": sum(1 for b in bills if b.totals_mismatch),
        "shifts": _shift_lines(db, d),
        "tablets": _tablet_warnings(db),
        "voids": len(voided),
        "voided_total": sum(b.total_paise for b in voided),
        "top": [(n, int(q), int(t)) for n, q, t in top],
        "wasted": int(wasted or 0),
        "day_status": day.status.value if day else None,
        "service": _service_lines(db, d),
    }


def _service_lines(db: Session, d: date) -> list[str]:
    """Table service leak signals for the email; empty for a counter-only shop."""
    from app.services.orders import service_report  # local: orders imports models

    r = service_report(db, d)
    out = []
    if r["changed_after_bill"]:
        n = len(r["changed_after_bill"])
        out.append(
            f"{n} bill(s) changed after printing: "
            + ", ".join(c["label"] for c in r["changed_after_bill"])
        )
    if r["cancellations"]:
        out.append(
            f"{sum(c['qty'] for c in r['cancellations'])} item(s) cancelled after sending to "
            f"the kitchen, worth {rupees(r['cancelled_value_paise'])}"
        )
    if r["cancelled_orders"]:
        out.append(f"{len(r['cancelled_orders'])} order(s) cancelled")
    if r["still_open"]:
        out.append(
            f"{len(r['still_open'])} order(s) not settled: "
            + ", ".join(o["label"] for o in r["still_open"])
        )
    return out


def _shift_lines(db: Session, d: date) -> list[str]:
    """One line per drawer shift: who, and whether the cash matched."""
    from app.services.shifts import shift_report  # local: shifts imports models only

    out = []
    for s in shift_report(db, d)["shifts"]:
        who = s["opened_by_name"]
        diff = s["difference_paise"]
        if diff is None:
            out.append(f"{who}: shift not ended (cash not counted)")
        elif diff == 0:
            out.append(f"{who}: cash matched ({rupees(s['counted_cash_paise'])})")
        else:
            word = "over" if diff > 0 else "short"
            out.append(
                f"{who}: {rupees(abs(diff))} {word} (counted {rupees(s['counted_cash_paise'])})"
            )
    return out


def _tablet_warnings(db: Session) -> list[str]:
    from app.services.health import warnings  # local: health imports billing

    return warnings(db)


def enqueue_daily(db: Session, shop: Shop, d: date) -> None:
    if not shop.email_daily:
        return
    f = daily_figures(db, d)
    subject = f"Sales {day_label(d)}: {rupees(f['total'])} from {f['bills']} bill" + (
        "" if f["bills"] == 1 else "s"
    )
    modes = [(PAYMENT[m], rupees(f["by_mode"].get(m, 0))) for m in ("cash", "upi", "card")]
    status = {
        "approved": "Day closed (count approved).",
        "submitted": "Count done, waiting for your approval.",
        "counting": "Day-end count started but not finished.",
        None: "No day-end count for this day.",
    }[f["day_status"]]
    body = (
        f"<p style='font-size:22px;margin:0'><b>{rupees(f['total'])}</b></p>"
        f"<p>{f['bills']} bills · GST collected {rupees(f['gst'])} · "
        f"wasted {rupees(f['wasted'])}</p>"
        + _table(modes)
        + (
            "<h3 style='font-size:15px'>Top items</h3>"
            + _table([(n, q, rupees(t)) for n, q, t in f["top"]], ("Item", "Qty", "Sales"))
            if f["top"]
            else "<p>No sales.</p>"
        )
        + f"<p>{escape(status)}</p>"
        + (
            "<h3 style='font-size:15px'>Cash drawer</h3><p>"
            + "<br>".join(escape(x) for x in f["shifts"])
            + "</p>"
            if f["shifts"]
            else ""
        )
        + (
            "<h3 style='font-size:15px;color:#b3261e'>Tablets need attention</h3><p>"
            + "<br>".join(escape(x) for x in f["tablets"])
            + "</p>"
            if f["tablets"]
            else ""
        )
        + (
            "<h3 style='font-size:15px;color:#b3261e'>Table service</h3><p>"
            + "<br>".join(escape(x) for x in f["service"])
            + " (details under Manage → Sales)</p>"
            if f["service"]
            else ""
        )
        + (
            f"<p>{f['voids']} voided bill(s) worth {rupees(f['voided_total'])}, "
            "not included above. Reasons are in the app under Manage → Sales.</p>"
            if f["voids"]
            else ""
        )
        + (
            f"<p style='color:#b3261e'>{f['mismatch']} bill(s) where the tablet's total "
            "differed from the server's: check them under Manage → Sales.</p>"
            if f["mismatch"]
            else ""
        )
    )
    text = (
        f"{subject}\n"
        + "\n".join(f"{a}: {b}" for a, b in modes)
        + f"\nGST {rupees(f['gst'])}\n{status}"
        + "".join(f"\nTablet: {x}" for x in f["tablets"])
        + (f"\nVoided: {f['voids']} bill(s), {rupees(f['voided_total'])}" if f["voids"] else "")
        + "".join(f"\nCash: {x}" for x in f["shifts"])
        + "".join(f"\nTables: {x}" for x in f["service"])
    )
    enqueue(
        db, shop, EmailKind.daily, f"daily:{d.isoformat()}", subject, _page(subject, body), text
    )


# ---------------------------------------------------------------- weekly export
def _csv(header: list[str], rows) -> dict:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")  # BOM: Excel opens the ₹ and names correctly


def enqueue_weekly(db: Session, shop: Shop, start: date, end: date) -> None:
    """Every bill, line, stock movement and wastage entry from start..end (inclusive)."""
    if not shop.email_weekly:
        return
    devices = dict(db.execute(select(Device.id, Device.code)).all())
    users = dict(db.execute(select(User.id, User.name)).all())
    names = {i.id: (i.name, i.base_unit.value) for i in db.scalars(select(Ingredient))}
    bills = db.scalars(
        select(Bill)
        .where(Bill.business_date.between(start, end))
        .order_by(Bill.sold_at)
        .options(selectinload(Bill.lines), selectinload(Bill.void))
    ).all()

    def r(p: int) -> str:
        return f"{p / 100:.2f}"

    files = {
        "bills.csv": _csv(
            [
                "invoice_no",
                "business_date",
                "sold_at",
                "device",
                "cashier",
                "payment",
                "taxable",
                "cgst",
                "sgst",
                "round_off",
                "total",
                "totals_mismatch",
                "status",
                "void_reason",
            ],
            [
                [
                    b.invoice_no,
                    b.business_date,
                    b.sold_at.isoformat(),
                    devices.get(b.device_id),
                    users.get(b.cashier_id),
                    b.payment_mode.value,
                    r(b.taxable_paise),
                    r(b.cgst_paise),
                    r(b.sgst_paise),
                    r(b.round_off_paise),
                    r(b.total_paise),
                    b.totals_mismatch,
                    b.status.value,
                    b.void.reason.value if b.void else "",
                ]
                for b in bills
            ],
        ),
        "bill_lines.csv": _csv(
            [
                "invoice_no",
                "item",
                "qty",
                "unit_price",
                "gst_rate_pct",
                "taxable",
                "cgst",
                "sgst",
                "total",
            ],
            [
                [
                    b.invoice_no,
                    ln.name_snapshot,
                    ln.qty,
                    r(ln.unit_price_paise),
                    ln.gst_rate_bp / 100,
                    r(ln.taxable_paise),
                    r(ln.cgst_paise),
                    r(ln.sgst_paise),
                    r(ln.total_paise),
                ]
                for b in bills
                for ln in sorted(b.lines, key=lambda x: x.position)
            ],
        ),
        "stock_movements.csv": _csv(
            ["business_date", "ingredient", "unit", "reason", "qty_change", "recorded_at"],
            [
                [
                    m.business_date,
                    *names.get(m.ingredient_id, ("?", "")),
                    m.reason.value,
                    m.qty_delta,
                    m.created_at.isoformat(),
                ]
                for m in db.scalars(
                    select(StockLedger)
                    .where(StockLedger.business_date.between(start, end))
                    .order_by(StockLedger.created_at)
                )
            ],
        ),
        "wastage.csv": _csv(
            ["business_date", "what", "qty", "reason", "value", "recorded_by", "note"],
            [
                [
                    w.business_date,
                    names.get(w.ingredient_id, ("menu item",))[0]
                    if w.ingredient_id
                    else "menu item",
                    w.qty,
                    w.reason.value,
                    r(w.value_paise),
                    users.get(w.created_by),
                    w.note,
                ]
                for w in db.scalars(
                    select(WastageEntry)
                    .where(WastageEntry.business_date.between(start, end))
                    .order_by(WastageEntry.created_at)
                )
            ],
        ),
    }
    label = f"{day_label(start)} – {day_label(end)}"
    subject = (
        f"Weekly data {label}: {len(bills)} bills, {rupees(sum(b.total_paise for b in bills))}"
    )
    body = (
        f"<p>All bills, bill lines, stock movements and wastage for {escape(label)}, "
        "as CSV files that open in Excel or Google Sheets. "
        "Keep them: they are also your backup.</p>"
    )
    enqueue(
        db,
        shop,
        EmailKind.weekly,
        f"weekly:{start.isoformat()}",
        subject,
        _page(subject, body),
        subject,
        [{"filename": n, "content": b64(data)} for n, data in files.items()],
    )


def week_before(today: date) -> tuple[date, date] | None:
    """On Mondays: the Monday..Sunday just ended. Other days: nothing to send."""
    if today.weekday() != 0:
        return None
    return today - timedelta(days=7), today - timedelta(days=1)


def enqueue_test(db: Session, shop: Shop) -> None:
    from app.core.time import utcnow

    now = utcnow()
    subject = "Chai POS: test email"
    body = (
        f"<p>Reports for <b>{escape(shop.name)}</b> will arrive at this address.</p>"
        f"<p style='color:#55626d'>Sent {escape(_ist_time(now))}.</p>"
    )
    enqueue(
        db, shop, EmailKind.test, f"test:{now.isoformat()}", subject, _page(subject, body), subject
    )

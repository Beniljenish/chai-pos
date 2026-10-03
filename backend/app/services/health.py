"""Tablet health and lost bills (README, "Bill safety").

Phase 4's gate is "7 days live, no lost bills", so a lost bill must be visible.
Each tablet reports, whenever it syncs, what it holds: the last invoice number
it printed per financial year, the bills still waiting to send, and the ones the
server refused. A number the tablet printed that the server never received AND
the tablet no longer holds is a lost bill: usually a wiped browser, a broken
tablet, or a bug. Nothing else can find it: the server cannot see a bill it never got.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import Bill, Device
from app.services.billing import invoice_number

STALE_PENDING = timedelta(hours=2)  # bills waiting longer than this: the tablet is stuck
UNSEEN = timedelta(hours=24)  # an active tablet silent this long: check on it
MAX_LISTED = 50


def record_report(db: Session, device: Device, report: dict) -> None:
    merged = dict(device.reported_seq_by_fy or {})
    for fy, seq in report["seq_by_fy"].items():
        merged[fy] = max(int(merged.get(fy, 0)), seq)  # only ever goes up
    device.reported_seq_by_fy = merged
    device.health = {
        "pending_bills": report["pending_bills"],
        "pending_ops": report["pending_ops"],
        "rejected": report["rejected"],
        "oldest_pending_at": report["oldest_pending_at"].isoformat()
        if report["oldest_pending_at"]
        else None,
        "held_seqs_by_fy": report["held_seqs_by_fy"],
        "persisted_storage": report["persisted_storage"],
        "app_version": report["app_version"],
    }
    now = utcnow()
    device.health_at = now
    device.last_seen_at = now


def resume_seq_by_fy(db: Session, device: Device, server: dict[str, int]) -> dict[str, int]:
    """Where a wiped tablet continues numbering: after the highest number either
    the server received or the tablet reported printing."""
    out = dict(server)
    for fy, seq in (device.reported_seq_by_fy or {}).items():
        out[fy] = max(out.get(fy, 0), int(seq))
    return out


def _missing(db: Session, device: Device) -> list[str]:
    held = (device.health or {}).get("held_seqs_by_fy", {})
    lost: list[str] = []
    for fy, top in sorted((device.reported_seq_by_fy or {}).items()):
        got = set(
            db.scalars(select(Bill.local_seq).where(Bill.device_id == device.id, Bill.fy == fy))
        )
        top = max([int(top), *got]) if got else int(top)
        holding = set(held.get(fy, []))
        for seq in range(1, top + 1):
            if seq not in got and seq not in holding:
                lost.append(invoice_number(device.code, fy, seq))
    return lost


def tablet_health(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    rows = []
    for d in db.scalars(select(Device).order_by(Device.code)):
        h = d.health or {}
        oldest = h.get("oldest_pending_at")
        oldest_dt = datetime.fromisoformat(oldest) if oldest else None
        missing = _missing(db, d)
        rows.append(
            {
                "id": d.id,
                "name": d.name,
                "code": d.code,
                "is_active": d.is_active,
                "last_seen_at": d.last_seen_at,
                "reported_at": d.health_at,
                "pending_bills": h.get("pending_bills", 0),
                "pending_ops": h.get("pending_ops", 0),
                "oldest_pending_at": oldest_dt,
                "stuck": bool(oldest_dt and now - oldest_dt > STALE_PENDING),
                "rejected": h.get("rejected", 0),
                "persisted_storage": h.get("persisted_storage"),
                "app_version": h.get("app_version"),
                "unseen": bool(
                    d.is_active and (d.last_seen_at is None or now - d.last_seen_at > UNSEEN)
                ),
                "missing_count": len(missing),
                "missing": missing[:MAX_LISTED],
            }
        )
    return rows


def warnings(db: Session) -> list[str]:
    """Plain lines for the daily email; empty when every tablet is fine."""
    out = []
    for t in tablet_health(db):
        if not t["is_active"]:
            continue
        name = f"{t['name']} ({t['code']})"
        if t["missing_count"]:
            out.append(
                f"{name}: {t['missing_count']} printed bill(s) never reached the server "
                f"(first: {t['missing'][0]})"
            )
        if t["stuck"]:
            out.append(f"{name}: {t['pending_bills']} bill(s) waiting to send for over 2 hours")
        if t["rejected"]:
            out.append(f"{name}: {t['rejected']} bill(s) refused by the server, check the tablet")
        if t["unseen"] and t["last_seen_at"] is not None:
            out.append(f"{name}: not seen for over a day")
    return out

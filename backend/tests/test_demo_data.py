"""The staging demo data (scripts.demo_data) still runs against the real API.

It drives every sync and owner route with a moving clock, so an API change that
breaks it shows here, not when the owner presses "Reset staging demo data".
"""

import json
import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Bill, DayCount, Order, Shift, StockLedger


def test_two_days_of_demo_data(tmp_path, monkeypatch):
    from scripts import demo_data

    owner, cashier = str(uuid.uuid4()), str(uuid.uuid4())
    keep = {
        "shop_id": str(uuid.uuid4()),
        "users": [
            {"id": owner, "name": "Owner", "role": "owner"},
            {"id": cashier, "name": "Cashier", "role": "cashier"},
        ],
    }
    (tmp_path / "keep.json").write_text(json.dumps(keep))
    monkeypatch.setenv("DEMO_KEEP", str(tmp_path / "keep.json"))
    monkeypatch.setattr(demo_data, "DAYS", 2)
    demo_data.main()

    db = mark_system(SessionLocal())
    try:
        assert db.scalar(select(func.count()).select_from(Bill)) > 200
        # Shifts closed with a count, days counted and closed, tables still eating now
        assert db.scalar(select(func.count()).where(Shift.counted_cash_paise.is_not(None))) >= 2
        assert db.scalar(select(func.count()).where(DayCount.status == "approved")) >= 1
        assert db.scalar(select(func.count()).where(Order.status != "settled")) >= 4
        # The owner buys enough: nothing is below zero
        negative = db.execute(
            select(StockLedger.ingredient_id)
            .group_by(StockLedger.ingredient_id)
            .having(func.sum(StockLedger.qty_delta) < 0)
        ).all()
        assert negative == []
    finally:
        db.close()

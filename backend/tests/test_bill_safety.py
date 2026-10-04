"""Bill safety: a printed bill that never reached the server is found, and a
wiped tablet never reprints a number already on a receipt.

Story: tablet C1 prints bills 1-6. Bills 1-3 sync. Then:
  - 4 is still waiting on the tablet (offline) -> held, not lost
  - 5 was refused by the server and sits on the tablet -> held, not lost
  - 6 was printed, then the browser storage was cleared -> LOST
The tablet had reported "printed up to 6" before the wipe. After the wipe it
must resume at 7, not at 4 (which would reprint C1/26-27/000004).
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.time import business_date, utcnow
from app.services.billing import financial_year
from tests.conftest import FakeDevice, build_catalogue

API = "/api/v1"


@pytest.fixture
def device(client, shop_a):
    build_catalogue(client, shop_a)
    return FakeDevice(client, shop_a)


def _report(client, h, device_id, **kw):
    body = {"seq_by_fy": {}, "pending_bills": 0, **kw}
    r = client.post(f"{API}/devices/{device_id}/report", json=body, headers=h)
    assert r.status_code == 204, r.text


def _health(client, h):
    return {t["code"]: t for t in client.get(f"{API}/devices-health", headers=h).json()}


def test_lost_bill_is_found_and_numbering_never_goes_back(client, shop_a, device):
    fy = financial_year(business_date(utcnow()))
    h = shop_a.cashier_h
    bills = [device.bill([("Masala tea", 1, [])]) for _ in range(6)]
    device.sync(bills[:3]).raise_for_status()
    waiting = (utcnow() - timedelta(hours=3)).isoformat()
    _report(
        client,
        h,
        device.device_id,
        seq_by_fy={fy: 6},
        pending_bills=1,
        rejected=1,
        oldest_pending_at=waiting,
        held_seqs_by_fy={fy: [4, 5]},
        persisted_storage=True,
    )
    t = _health(client, shop_a.owner_h)["C1"]
    assert t["missing"] == [f"C1/{fy}/000006"] and t["missing_count"] == 1
    assert (t["pending_bills"], t["rejected"], t["stuck"]) == (1, 1, True)
    assert t["persisted_storage"] is True

    # The browser is wiped: the tablet now holds nothing and reports nothing printed.
    _report(client, h, device.device_id, seq_by_fy={fy: 0}, pending_bills=0)
    state = client.get(f"{API}/devices/{device.device_id}/sync-state", headers=h).json()
    assert state["last_seq_by_fy"][fy] == 6  # resume at 7, never reprint 4-6
    t = _health(client, shop_a.owner_h)["C1"]
    assert t["missing"] == [f"C1/{fy}/{n:06d}" for n in (4, 5, 6)]


def test_a_healthy_tablet_shows_nothing_missing(client, shop_a, device):
    fy = financial_year(business_date(utcnow()))
    device.sync([device.bill([("Masala tea", 1, [])]) for _ in range(3)]).raise_for_status()
    _report(client, shop_a.cashier_h, device.device_id, seq_by_fy={fy: 3})
    t = _health(client, shop_a.owner_h)["C1"]
    assert t["missing"] == [] and not t["stuck"] and not t["unseen"]
    assert t["last_seen_at"] is not None


def test_health_is_owner_only_and_per_shop(client, shop_a, shop_b, device):
    _report(client, shop_a.cashier_h, device.device_id, seq_by_fy={"26-27": 2})
    assert client.get(f"{API}/devices-health", headers=shop_a.cashier_h).status_code == 403
    assert [
        t["code"] for t in client.get(f"{API}/devices-health", headers=shop_b.owner_h).json()
    ] == ["C1"]  # shop B's own tablet only
    assert _health(client, shop_b.owner_h)["C1"]["missing"] == []


def test_report_rejects_nonsense(client, shop_a, device):
    r = client.post(
        f"{API}/devices/{device.device_id}/report",
        json={"seq_by_fy": {"2026": 5}, "pending_bills": -1},
        headers=shop_a.cashier_h,
    )
    assert r.status_code == 422


def test_daily_email_warns_about_tablets(client, shop_a, device):
    from app.db.session import SessionLocal
    from app.db.tenancy import bind_tenant
    from app.services.reports import daily_figures

    fy = financial_year(business_date(utcnow()))
    _report(
        client,
        shop_a.cashier_h,
        device.device_id,
        seq_by_fy={fy: 2},
        pending_bills=1,
        oldest_pending_at=(datetime.now(UTC) - timedelta(hours=5)).isoformat(),
        held_seqs_by_fy={fy: [2]},
    )
    with SessionLocal() as s:
        bind_tenant(s, shop_a.shop.id)
        lines = daily_figures(s, business_date(utcnow()))["tablets"]
    assert lines == [
        f"Counter 1 (C1): 1 printed bill(s) never reached the server (first: C1/{fy}/000001)",
        "Counter 1 (C1): 1 bill(s) waiting to send for over 2 hours",
    ]


def test_a_report_with_other_counters_is_still_taken(client, shop_a, device):
    """Tablets keep their kitchen-ticket counter next to the invoice counters
    (`kot:<date>`). An older app sent it in seq_by_fy; the report used to be
    refused whole (422), so the owner never heard from that tablet again."""
    fy = financial_year(business_date(utcnow()))
    _report(
        client,
        shop_a.cashier_h,
        device.device_id,
        seq_by_fy={fy: 4, "kot:2026-10-04": 7},
        pending_bills=30,
        held_seqs_by_fy={fy: [3, 4], "kot:2026-10-04": [1]},
    )
    (t,) = _health(client, shop_a.owner_h).values()
    assert t["pending_bills"] == 30

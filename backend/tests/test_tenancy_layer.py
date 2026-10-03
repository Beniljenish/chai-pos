"""Unit tests for the tenancy hooks themselves, below the HTTP layer."""

import pytest
from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.db.tenancy import TenantScopeError, bind_tenant
from app.models import Device, User


def test_unbound_session_refuses_tenant_queries(shop_a):
    db = SessionLocal()
    with pytest.raises(TenantScopeError):
        db.scalars(select(User)).all()
    db.close()


def test_unbound_session_refuses_tenant_writes(shop_a):
    db = SessionLocal()
    db.add(Device(shop_id=shop_a.shop.id, name="x", code="C9"))
    with pytest.raises(TenantScopeError):
        db.flush()
    db.close()


def test_bound_session_cannot_write_into_another_shop(shop_a, shop_b):
    db = bind_tenant(SessionLocal(), shop_a.shop.id)
    db.add(Device(shop_id=shop_b.shop.id, name="x", code="C9"))
    with pytest.raises(TenantScopeError):
        db.flush()
    db.close()


def test_bound_session_stamps_shop_id_on_new_rows(shop_a):
    db = bind_tenant(SessionLocal(), shop_a.shop.id)
    d = Device(name="auto", code="C9")
    db.add(d)
    db.flush()
    assert d.shop_id == shop_a.shop.id
    db.rollback()
    db.close()


def test_bulk_update_is_scoped(shop_a, shop_b):
    db = bind_tenant(SessionLocal(), shop_a.shop.id)
    db.execute(update(Device).values(name="renamed by A"))
    db.commit()
    db.close()

    check = bind_tenant(SessionLocal(), shop_b.shop.id)
    assert check.scalar(select(Device.name)) == "Counter 1"
    check.close()


def test_join_from_tenant_table_is_scoped(shop_a, shop_b):
    db = bind_tenant(SessionLocal(), shop_a.shop.id)
    rows = db.execute(select(User.id, Device.id).join(Device, Device.shop_id == User.shop_id)).all()
    assert rows and all(u in {shop_a.owner.id, shop_a.cashier.id} for u, _ in rows)
    db.close()


def test_shops_table_is_scoped_too(shop_a, shop_b):
    from app.models import Shop

    db = bind_tenant(SessionLocal(), shop_a.shop.id)
    assert db.scalars(select(Shop.id)).all() == [shop_a.shop.id]
    db.close()

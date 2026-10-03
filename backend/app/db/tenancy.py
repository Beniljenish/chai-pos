"""Automatic tenant isolation.

Every request gets a Session tagged with the caller's shop_id. Two SQLAlchemy
event hooks then make cross-shop access impossible for ORM code:

1. do_orm_execute: every SELECT / UPDATE / DELETE touching a TenantScoped model
   gets `WHERE shop_id = <current shop>` added automatically
   (SQLAlchemy's documented with_loader_criteria pattern).
2. before_flush: every new or changed TenantScoped row is stamped with, or
   checked against, the current shop_id.

A session with neither a shop_id nor an explicit `system` flag refuses to run
tenant queries at all. That turns "forgot to scope this query" from a silent
data leak into a loud error in tests.

Why not Postgres row-level security (RLS)? RLS is stronger (it also covers raw
SQL), but it is harder to debug and to test. Revisit when going multi-shop.
"""

import uuid

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.db.base import TenantScoped
from app.models import Shop

SHOP_KEY = "shop_id"
SYSTEM_KEY = "system"


class TenantScopeError(RuntimeError):
    pass


def bind_tenant(session: Session, shop_id: uuid.UUID) -> Session:
    session.info[SHOP_KEY] = shop_id
    return session


def mark_system(session: Session) -> Session:
    """For the few pre-tenant operations (login, refresh, seeding). Use sparingly."""
    session.info[SYSTEM_KEY] = True
    return session


def _touches_tenant_table(state: ORMExecuteState) -> bool:
    return any(issubclass(m.class_, TenantScoped | Shop) for m in state.all_mappers)


@event.listens_for(Session, "do_orm_execute")
def _scope_queries(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load:
        return
    info = state.session.info
    if info.get(SYSTEM_KEY):
        return
    shop_id = info.get(SHOP_KEY)
    if shop_id is None:
        if _touches_tenant_table(state):
            raise TenantScopeError("Tenant query on a session with no shop bound")
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.shop_id == shop_id,
            include_aliases=True,
        ),
        # The shops table is the tenant root (it has no shop_id column), so it
        # gets its own rule: a tenant session can only ever see its own shop row.
        with_loader_criteria(Shop, lambda cls: cls.id == shop_id, include_aliases=True),
    )


@event.listens_for(Session, "before_flush")
def _stamp_and_check(session: Session, _ctx, _instances) -> None:
    if session.info.get(SYSTEM_KEY):
        return
    shop_id = session.info.get(SHOP_KEY)
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if not isinstance(obj, TenantScoped):
            continue
        if shop_id is None:
            raise TenantScopeError("Write to a tenant table on a session with no shop bound")
        if obj.shop_id is None:
            obj.shop_id = shop_id
        elif obj.shop_id != shop_id:
            raise TenantScopeError("Attempt to write a row belonging to another shop")

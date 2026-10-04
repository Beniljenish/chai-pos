"""SQL for the parts of the demo data that are not a plain table dump: the
shop's settings (its row is kept, so it is updated) and the demo staff, who
must set their own password at first login (the owner gives them one in Staff).

    DATABASE_URL=<the local demo database> python -m scripts.demo_export > extra.sql
"""

from psycopg import sql
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.tenancy import mark_system
from app.models import Shop, User

SHOP_COLS = [
    "name",
    "gst_type",
    "gstin",
    "state_code",
    "address",
    "invoice_prefix",
    "cash_shifts",
    "max_discount_bp",
]
USER_COLS = [
    "id",
    "shop_id",
    "name",
    "phone",
    "role",
    "password_hash",
    "is_active",
    "must_change_password",
]


def lit(v) -> sql.Literal:
    return sql.Literal(v.value if hasattr(v, "value") else v)


def main() -> None:
    db = mark_system(SessionLocal())
    (shop,) = db.scalars(select(Shop)).all()
    update = sql.SQL("UPDATE shops SET {} WHERE id = {};").format(
        sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(c), lit(getattr(shop, c))) for c in SHOP_COLS
        ),
        lit(str(shop.id)),
    )
    print(update.as_string(None))
    insert = sql.SQL("INSERT INTO users ({}) VALUES ({});")
    for u in db.scalars(select(User).where(User.phone.like("90000200__"))):
        vals = [str(u.id), str(u.shop_id), u.name, u.phone, u.role, u.password_hash, True, True]
        row = insert.format(
            sql.SQL(", ").join(map(sql.Identifier, USER_COLS)),
            sql.SQL(", ").join(map(lit, vals)),
        )
        print(row.as_string(None))
    db.close()


if __name__ == "__main__":
    main()

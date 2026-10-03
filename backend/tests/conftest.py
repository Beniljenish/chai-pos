import os

# Must be set before the app (and its engine) is imported.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://chai:chai@localhost:5432/chai_pos_test")
os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789")

from dataclasses import dataclass  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.db.tenancy import mark_system  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Device, GstType, Role, Shop, User  # noqa: E402

PASSWORD = "correct-horse-1"


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    """Build the test schema with the real migrations, not create_all().
    That way the tests also prove the migrations work."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE refresh_tokens, devices, users, shops CASCADE"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@dataclass
class ShopFixture:
    shop: Shop
    owner: User
    cashier: User
    device: Device
    owner_token: str
    cashier_token: str

    @property
    def owner_h(self) -> dict:
        return {"Authorization": f"Bearer {self.owner_token}"}

    @property
    def cashier_h(self) -> dict:
        return {"Authorization": f"Bearer {self.cashier_token}"}


_counter = {"n": 0}


def _phone() -> str:
    _counter["n"] += 1
    return f"9{_counter['n']:09d}"


def make_shop(client: TestClient, name: str) -> ShopFixture:
    db = mark_system(SessionLocal())
    shop = Shop(name=name, gst_type=GstType.regular, state_code="33")
    db.add(shop)
    db.flush()
    owner = User(
        shop_id=shop.id,
        name=f"{name} owner",
        phone=_phone(),
        role=Role.owner,
        password_hash=hash_password(PASSWORD),
    )
    cashier = User(
        shop_id=shop.id,
        name=f"{name} cashier",
        phone=_phone(),
        role=Role.cashier,
        password_hash=hash_password(PASSWORD),
    )
    device = Device(shop_id=shop.id, name="Counter 1", code="C1")
    db.add_all([owner, cashier, device])
    db.commit()
    db.close()

    def token(u: User) -> str:
        r = client.post("/api/v1/auth/login", json={"phone": u.phone, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    return ShopFixture(shop, owner, cashier, device, token(owner), token(cashier))


@pytest.fixture
def shop_a(client) -> ShopFixture:
    return make_shop(client, "Shop A")


@pytest.fixture
def shop_b(client) -> ShopFixture:
    return make_shop(client, "Shop B")

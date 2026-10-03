# Chai POS

Billing and stock-accuracy app for tea and juice shops: GST bills that work
offline, SOP-based stock deduction, and a day-end report of what went missing.

Spec and phase gates: [docs/SPEC.md](docs/SPEC.md)

## Run it locally

```bash
docker compose up --build          # API on http://localhost:8000, docs at /docs
docker compose exec api sh -c "SEED_PASSWORD=devpass123 python -m scripts.seed"
```

Without Docker (needs Python 3.12+ and a local Postgres):

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env               # then edit JWT_SECRET
alembic upgrade head
uvicorn app.main:app --reload
pytest                             # uses the chai_pos_test database
```

## How the backend is put together (Phase 0)

```
backend/app/
  api/         HTTP only: routes, request parsing, status codes
    deps.py    who is calling -> TenantContext + a shop-bound DB session
  services/    business logic, no HTTP (auth now; billing, stock later)
  db/
    tenancy.py automatic shop_id isolation  <- read this file first
  models/      SQLAlchemy tables
  schemas.py   Pydantic request/response shapes + validation
```

### Decisions and trade-offs

**Tenant isolation is automatic, not remembered.** Every request's DB session
is bound to the caller's `shop_id`, taken only from the signed JWT. SQLAlchemy
event hooks add `WHERE shop_id = …` to every query on a shop-owned table and
stamp or check `shop_id` on every write. A session with no shop bound refuses
tenant queries entirely. The gate test (`tests/test_tenant_gate.py`) also fails
if anyone adds an `/{id}` route without adding it to the gate.
*Trade-off:* raw SQL strings bypass the hooks. Postgres row-level security would
cover that too; it is planned for the move to multi-shop.

**404, not 403, for another shop's ids** so a caller cannot even confirm an id
exists.

**Short access tokens, rotating refresh tokens.** Access = 15 min. Refresh = 7
days, stored as SHA-256 hashes, rotated on every use. Replaying an old refresh
token revokes the whole login family (stolen-token detection). The user row is
re-checked on every request, so deactivating a cashier works instantly.

**Sync SQLAlchemy, not async.** Simpler to read and debug; FastAPI runs sync
handlers in a thread pool. At one shop's load this is far from a bottleneck.

**Phone is globally unique** so login is just phone + password. Trade-off: one
person can't use the same number at two shops. Revisit for multi-shop.

**Tests hit real Postgres, built by the real migrations**, not SQLite and
`create_all()`, so the tests also prove the migrations work. CI runs
`alembic check` to catch model changes without a migration.

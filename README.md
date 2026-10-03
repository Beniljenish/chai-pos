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

## Phase 1: catalogue, recipes, stock ledger

```
app/models/catalogue.py   ingredients, pack units, menu, versioned recipes, modifiers,
                          stock receipts, prep batches, the append-only stock ledger
app/services/recipes.py   recipe versions, resolve-at-time, juice yield maths
app/services/stock.py     stock-in (pack conversion + sanity check), prep batches, on hand
```

### Decisions and trade-offs

**Quantities are `NUMERIC(14,3)`, never floats.** 250 ml of juice at 450 ml/kg is
555.556 g of oranges; floats would drift, integer grams would round every glass.
API responses send them as strings (`"555.556"`) so JavaScript never turns them
into floats either.

**Stock on hand = `SUM(stock_ledger.qty_delta)`.** No stored balance that can
disagree with history. A Postgres trigger rejects `UPDATE`/`DELETE` on the
ledger, so even hand-written SQL can't rewrite it; corrections are new rows.
*Trade-off:* summing gets slower as rows grow; the planned fix is a snapshot per
day-close, not a running balance.

**Recipes are immutable versions.** `PUT .../recipe` adds version N+1 with an
`effective_from` time. `GET .../recipe?at=<time>` returns what was in force then.
Phase 2 bills store the recipe id they used, so editing an SOP never rewrites
past consumption.

**Prep recipes use raw ingredients only (v1).** Decoction from milk: yes. A prep
made from another prep: rejected. Avoids cycle detection and multi-level unwinding.

**Negative stock is shown, not blocked.** A batch made before the morning's
milk entry must never stop billing. `/stock` flags it as `is_negative`.

**Pack units are add-only.** Changing "1 crate = 24 packets" would silently
change the meaning of past receipts; receipts also store the conversion used.

**Stock-in sanity check.** More than 3x the median of the last 10 receipts needs
`confirm_large: true` (409 otherwise). Applies once there are 3+ receipts.

**`/stock` is owner-only** so Phase 3's blind counts stay blind.

**`/catalogue` has an ETag.** A billing device sends `If-None-Match` and gets an
empty 304 when nothing changed, which matters on patchy shop internet.

### Gate tests
- `test_phase1_gate.py`: 200 random stock-ins and prep batches replayed
  independently must equal `/stock` exactly; recipe versions pinned in time;
  raw-SQL `UPDATE`/`DELETE` on the ledger fails.
- Each gate test was checked by deliberately breaking the code it guards
  (ignoring the recipe date, rounding prep yield, skipping pack conversion)
  and confirming it fails.
- `test_tenant_gate.py` now covers **every method** on every `/{id}` route, plus
  another shop's ids smuggled inside request bodies.

## Hosting: Supabase Postgres

Production database: Supabase project `chai-pos` (ref `dffvdkxprmoxytbbummz`,
Postgres 17, region `ap-northeast-2` Seoul). CI and Docker Compose also use
Postgres 17 so tests run on the same major version.

**Supabase-specific security.** Supabase publishes every `public` table through
its Data API with a public "anon" key. Migration `d9b48b507dcc` turns on row-level
security with no policies (deny all) on every table and revokes the Data API
roles' grants. The backend connects as the table owner, so it is unaffected.
`tests/test_database_security.py` fails if any new table lacks RLS.
Supabase's linter will list "RLS enabled, no policy" as INFO: that is intended.

**Applying migrations to Supabase.** From any machine that can reach the DB:
`DATABASE_URL=<supabase session pooler URL> alembic upgrade head`.
Without direct access: `alembic upgrade <current>:head --sql`, unescape `%%` -> `%`,
review, and apply the SQL (it updates `alembic_version` too).

**Connection string (Phase 4).** Use the **session pooler** (port 5432) from the
Supabase dashboard's Connect button, with the `postgresql+psycopg://` prefix. The
transaction pooler (6543) breaks psycopg's prepared statements unless
`prepare_threshold=None` is set. The password goes only into the host's env
settings, never into the repo.

## Phase 2a: GST and bill sync

```
app/services/gst.py       pure GST maths (paise, ROUND_HALF_UP); TypeScript twin in 2b
shared/gst_cases.json     test vectors BOTH implementations must pass
app/services/billing.py   idempotent bill ingest, invoice numbers, stock deduction
app/models/billing.py     bills, bill_lines, bill_line_modifiers
```

### Decisions and trade-offs

**One door for bills: `POST /sync/bills`.** Online and offline sales use the same
path, so the offline path is exercised on every sale, not just during outages.

**Idempotent by device-generated id.** Same id + same content (sha256) = harmless
`duplicate`. Same id + different content = `rejected` (bug or tampering). Each
bill saves in its own savepoint, so one bad bill never blocks a batch.

**Accept-and-flag totals.** The printed invoice is the legal record, so the books
store the printed totals. The server recalculates with `gst.py` and stores that
in `server_totals`; any difference sets `totals_mismatch` for the owner to review
(`GET /bills?mismatch_only=true`). Rejecting would lose a real sale and leave a gap
in the invoice series; silently overwriting would make books disagree with the
customer's invoice.

**Invoice numbers `C1/26-27/000123`.** Per device, per financial year (Apr-Mar),
15 characters (GST limit 16). Two offline devices can never collide. The server
checks the number matches the device code, FY and sequence, and the database
enforces uniqueness.

**Business date is shop-local (IST).** A sale at 00:10 IST belongs to that day,
even though it is still the previous day in UTC. Bills more than 10 minutes in the
device's future, or older than 30 days, are rejected.

**Stock uses the recipe version the device sold under**, scaled by modifiers
(`Large` = x1.5) plus modifier deltas, and never below zero per ingredient.
One ledger row per ingredient per bill, so Phase 3 voids can reverse a bill exactly.

### Gate tests
- `test_phase2a_gate.py`: 20 bills, shuffled, random batches, every batch sent
  twice, plus a full resend and a same-id-different-content bill: exactly 20 bills,
  invoice numbers 1..20 with no gaps, stock deducted exactly once.
- `test_gst.py`: shared vectors + 5,000 random bills against invariants.
- Verified by sabotage: banker's rounding, skipped inclusive adjustment, reused id
  treated as duplicate, double stock deduction, ignored modifier scale, negative
  consumption, missing rollback after a DB conflict. All caught.

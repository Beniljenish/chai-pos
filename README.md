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

### Fix found in staging: packaging does not scale with size

Staging data showed 17.5 paper cups used: the "Large" modifier multiplied the whole recipe by 1.5, cups included. Ingredients now have `scales_with_size` (default true; false for cups, lids, straws). Scale factors skip those; modifier deltas still apply to them, so if a shop uses a bigger cup for Large, the Large modifier can swap `Paper cup -1` for `Large cup +1` with no new code. The flag sits on the ingredient rather than each recipe line: a cup is one per serving in every recipe, the owner sets it once, and recipe versions (the history of what was used) stay untouched.

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

## Phase 2b: the billing app (`frontend/`)

React + Vite + TypeScript, installable as a PWA, works with no internet.

```
src/lib/gst.ts        GST in TypeScript (BigInt, integer-only); passes shared/gst_cases.json
                      AND reproduces 2,000 Python answers exactly (shared/gst_crosscheck.json)
src/lib/db.ts         IndexedDB (Dexie): settings, cached menu, invoice counters, bills/outbox
src/lib/billing.ts    saveBill: next invoice number + bill in ONE transaction
src/lib/sync.ts       syncOnce + SyncWorker (after each sale, on reconnect, on focus, every 30 s)
src/lib/api.ts        API client: access token in memory, refresh token in IndexedDB
src/app/              screens: login, tablet setup, billing + till, receipt, today's bills
```

Run it: `cd frontend && npm install && npm run dev` (backend on :8000).
Tests: `npm test`; gate against a live backend:
`GATE_API_URL=http://localhost:8000/api/v1 GATE_PASSWORD=... npm run test:gate`.

### Decisions and trade-offs

**Saving a bill never touches the network.** It is a local IndexedDB transaction
that takes the next invoice number and writes the bill together; a crash can't
leave a gap or a duplicate.

**Refresh token in IndexedDB** so the tablet stays logged in across restarts while
offline; the access token lives only in memory. Mitigation: a strict Content
Security Policy (scripts only from the app itself, connections only to the app and
the API), no third-party scripts, no inline scripts. Billing never needs a valid
login; only sending does, so an expired login never stops a sale.

**Wiped tablet protection.** If browser storage is cleared, the invoice counter
would restart at 1. On every online start the app reads
`GET /devices/{id}/sync-state` and never lets its counter fall below the server's.
It also requests persistent storage so the browser doesn't evict the outbox.

**Tablet setup is owner-only, once per tablet.** Each tablet has its own invoice
series; two tablets sharing one would print duplicate numbers. After setup, any
owner or cashier logs in on it whenever they need.

**Integer-only GST in TypeScript (BigInt).** Testing showed float `Math.round`
also gives the right answers at shop-sized amounts; BigInt is kept as a safety
margin because it is exact at any size.

**iOS:** data is only reliably kept once the app is added to the home screen.
Bluetooth thermal printing isn't possible from a web app on iOS (Android Chrome
can, via Web Bluetooth, in a later phase).

### Gate tests
- `src/lib/sync.gate.test.ts` (runs in CI against the real backend + Postgres):
  20 bills made with no network, then synced over a broken connection where 30% of
  requests never arrive and 25% arrive but **the reply is lost**. Result: outbox
  empty, server holds each bill exactly once, no totals mismatches.
- `e2e/billing.spec.ts` (Playwright, CI): log in, set up the tablet, sell, go
  offline, keep selling, **reload the app with no network**, come back online, all
  bills sent once. Screenshots are uploaded as a CI artifact.

## Staging on Vercel

Two Vercel projects from this one repo:

| Project | Root directory | What it is |
|---|---|---|
| `chai-pos-api` | `backend/` | FastAPI as one Python function (entrypoint in `pyproject.toml`, region `icn1` Seoul in `backend/vercel.json`) |
| `chai-pos-app` | `frontend/` | The PWA as static files (`frontend/vercel.json`: SPA rewrite, security headers, no-cache on the service worker) |

Environment variables (set in Vercel, never in the repo):

- API: `DATABASE_URL` (Supabase **transaction pooler**, port 6543, driver `postgresql+psycopg://`), `DB_SERVERLESS=true`, `JWT_SECRET`, `ENV=staging`, `CORS_ORIGINS=["https://<app domain>"]`
- App: `VITE_API_URL=https://<api domain>/api/v1` (baked in at build time, also into the CSP)

### Decisions and trade-offs

- **Function region Seoul, next to the database.** Vercel's default is US East; every bill sync makes several queries, and each would cross the Pacific (~180 ms each). Shop to Seoul is one hop; function to DB is then ~1 ms.
- **`DB_SERVERLESS=true`: no connection pool, no prepared statements.** A serverless instance can be frozen between requests, so pooled connections go stale; Supabase's transaction pooler hands each transaction to any Postgres backend, so a statement prepared on one is missing on the next. `NullPool` plus psycopg `prepare_threshold=None` avoids both. Tested in `tests/test_serverless_db.py`.
- **Cold starts accepted for staging.** The first request after idle takes a few seconds. The app does not care: bills are saved on the device first and the sync worker retries.
- **Migrations are not run on deploy.** They are applied to Supabase deliberately after a PR merges (see the Supabase section), so a deploy can never change the schema by surprise.

## Phase 3a: owner stock screen

The owner's **Stock** tab (cashiers see **Prep** instead): stock on hand, stock-in by pack, a one-time opening count, logging decoction batches, and the history behind every number.

### Decisions and trade-offs

- **Opening stock once per ingredient** (`stock_openings`, unique per shop and ingredient). A "set stock to X" button usable any time would silently absorb theft and wastage, which is exactly what day-end variance exists to catch. After the opening count, every change needs a reason.
- **Openings have their own table, not just a ledger row.** The ledger forbids zero movements, but an opening that matches the system (often zero for a new shop) still has to be remembered. The table also keeps what was counted ("3 packets + 200 ml") and what the system thought before (`system_qty`), so sales made before the first count are visible, not hidden.
- **Cashiers log batches but never see stock levels.** They make the decoction, so they log it (otherwise milk never goes down and decoction goes negative). Seeing expected quantities would defeat blind day-end counts.
- **Owner screens are online-only.** They edit the shop's records; working from a stale offline copy would be worse than a clear "needs internet" message. Billing stays fully offline.
- **Entry by pack, display in L/kg.** Staff count packets and crates; the total is previewed, and the server's conversion is the one stored.

## Phase 3b: recipes (SOPs) and ingredients

The owner's tab is now **Manage**, with **Stock** and **Recipes** inside it (Shop & GST joins next), so phones keep one row of tabs.

- **Recipes:** every drink and batch with its current SOP; tap to edit. Saving creates a new version ("Save as version 3"), with the full history and who changed what. Fresh juice is edited as a yield ("1 kg gives 450 ml, glass 250 ml") and the fruit per glass is worked out, matching the server's formula.
- **Ingredients:** add items (unit chosen once: every stock number is kept in it), add pack sizes (never edited, because past deliveries were counted with them), and tick "Same amount for every size" for cups, lids and straws. New "pieces" ingredients start ticked.

### Decisions and trade-offs

- **History is owner-only and names who changed it.** An SOP that can quietly change is not an SOP; "who set tea to 120 ml?" must have an answer.
- **Recipe lines are listed by ingredient name.** They were ordered by internal ID, so the same SOP could read in a different order on another database.
- **The editing tablet reloads its menu right after a save,** so its next sale uses the new version. Other tablets pick it up on their next menu refresh (the menu has an ETag, so that is one small request); bills already sold always keep the version they were sold under.
- **Validation in plain words, before saving** ("Choose an ingredient on every row, or remove the empty row"), mirrored by the server's own checks.

## Phase 3c: shop details and GST

**Manage → Shop & GST**: shop name and address, GST registration (not registered / composition / regular, each saying what it will print), GSTIN with live checking, a preview of how a real menu item will print, and **menu prices**: price, category, GST rate, whether the price includes GST, on/off the menu, and new items.

### Decisions and trade-offs

- **The GSTIN's check digit is verified** (server and app, same test vectors). The format check alone accepted any mistyped number, which would then be printed on every tax invoice.
- **Registered shops must have a GSTIN, and the shop's state comes from it.** The first two digits are the state of registration, and the state decides CGST+SGST, so they cannot be allowed to disagree. The rule is checked only when GST settings change, so a shop saved before the rule can still be renamed.
- **GST rate per item is limited to the current slabs** (0, 5, 18, 40% since GST 2.0 on 22 Sept 2025). Cafe and restaurant service is 5% without input tax credit. A free number field invites 50 instead of 500.
- **Receipt fixes:** a bill of supply (composition) now prints the GSTIN and the full required line ("…not eligible to collect tax on supplies"); a tax invoice prints CGST and SGST **with their rates**, one row per rate when a bill mixes 5% and 18% items.
- **Known gap:** a reprinted bill uses the shop's *current* GSTIN, not the one at the time of sale. GST type is already stored per bill; storing the GSTIN too changes the sync payload, so it is a separate change.

## Phase 3d: wastage, the blind day-end count, and variance

**Cashier → Stock** (batches, wastage, count; never stock levels or rupees). **Owner → Manage → Day end** (the same, plus the variance report and approval).

    expected closing = opening + stock-in + batches made − batches used
                       − sales (by recipe version, with modifiers) − wastage
    variance         = counted − expected        (negative = missing)
    adherence %      = expected usage ÷ actual usage × 100

### Decisions and trade-offs

- **The phase gate is a hand-worked day** (`tests/test_phase3_gate.py`): every number is worked out in the docstring and must match to the paisa. Three deliberate bugs (no late-bill correction, "Less sugar" adding sugar back, rounding down) were each caught by it.
- **Blind counts for staff; reconciliation for the owner.** A cashier's count sheet and submit reply never contain expected quantities (the field is left out of the response, not just hidden), and items outside tolerance get one "count again" with no numbers. The owner's sheet shows each item's expected balance with "Matches" and the live difference, and an owner count goes straight to the report without a recount prompt: the owner is reconciling, not being checked.
- **Tolerance is measured against usage, not stock level** (±3% default, ±8% milk and fruit): 500 ml missing out of 4 L used is a problem; out of 40 L in stock it would hide.
- **Approval makes the count the truth** with a `count_adjustment` row (the ledger is still never edited), and freezes that day's expected, cost and variance so a closed day's report never shifts.
- **Late bills.** A bill from a closed day that syncs afterwards left the shelf before the count, so a compensating row keeps stock equal to the count, and the report shows how much of the day's "missing" those late bills explain.
- **Wastage of a drink deducts its whole recipe;** "free" and "theft" are owner-only reasons. Values are at cost when recorded.
- **Cost of a batch item** (decoction) is worked out from its batch recipe and the raw ingredients' latest prices. Items with no purchase price yet show "no price yet" instead of a misleading ₹0.
- **Close after midnight:** the screen offers today or yesterday; the count belongs to the business day being closed.
- **Found by the browser test, not the unit tests:** the screen loads the sheet and the report at the same moment, and both tried to create the day's record, so one crashed. Reads no longer write, and creation survives two tablets submitting at once (a regression test runs six simultaneous requests).

**Not in this PR (next):** shifts and cash, voiding bills, sales reports, the 30-day adherence trend, approval for large wastage.

## Reports by email (Resend)

**Manage → Shop & GST → Reports by email**: the address, and four switches: daily sales summary (7:00 AM IST, yesterday's sales), day-end report (when the owner closes a day), weekly data export (Mondays: CSV files of every bill, line, stock movement and wastage entry), and every bill (off by default). A **Send test email** button checks the whole path.

Server settings (Vercel env, API project): `RESEND_API_KEY` (secret), `EMAIL_FROM` (default `Chai POS <reports@beniljenish.dev>`, a verified Resend domain), `CRON_SECRET` (Vercel Cron sends it as a bearer token; without it the cron endpoint refuses everything).

### Decisions and trade-offs

- **Outbox, not "send now".** Every email is first a row (`email_outbox`) written in the same transaction as its event: the bill email exists if and only if the bill does. Delivery happens after, never raises into the caller, and is retried (next sync, next approval, the daily cron) up to 5 times. A provider outage never blocks billing or loses an email.
- **Exactly once.** Each email has a dedupe key (`bill:<id>`, `daily:<date>`, `weekly:<monday>`) that is unique per shop and is sent to Resend as the idempotency key, so a resent bill, a retried cron or a crash between "sent" and "marked sent" cannot produce a second email.
- **Per-bill emails go in batches** (one Resend call per sync, up to 100 messages): one call instead of 50 keeps far inside Resend's rate limit and adds well under a second to a sync.
- **One cron a day** (Vercel's free plan allows exactly that) at 01:30 UTC = 07:00 IST: yesterday is a complete day by then, even for shops that close after midnight.
- **HTML-escaped**: item and shop names are shop data; a name like `<b>Chai</b>` is shown, not rendered.
- **CSV with a BOM** so Excel opens ₹ and names correctly.

## Phase 3e: new drinks and options on the bill

Manage → Recipes → **+ New drink** asks for the name, price and GST, then opens the recipe editor straight away, so no drink is left without a recipe by accident. **Options on the bill** (Large, Less sugar, Extra ginger) are created and edited in the same screen: price change, size, ingredient changes, and which drinks offer them. The drink editor (Recipes and Shop & GST) also has a tick-list of options.

### Decisions and trade-offs
- **Assign from both sides.** "Which drinks get Large?" is asked per option; "what does Ginger tea offer?" is asked per drink. `PUT /modifiers/{id}/menu-items` replaces only that option's links; `PUT /menu-items/{id}/modifiers` replaces only that drink's. Links to drinks taken off the menu are kept and sent back unchanged.
- **Direction + number, not signed numbers.** Many phone number pads have no minus key, so "Less sugar 5 g" is a *− less* picker plus 5.
- **Live preview uses the server's rule** (`consumption_for_line`): the recipe times the size, except things that do not grow with size (cups), plus the option's own changes, never below zero. Unit tests pin the two to the same numbers.
- **Two calls, retry-safe.** Saving creates or updates the option, then its drinks. If the second call fails, the editor keeps the new id, so retrying does not create a duplicate.

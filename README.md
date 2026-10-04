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
alembic upgrade heads
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
`DATABASE_URL=<supabase session pooler URL> alembic upgrade heads`.
Without direct access: `alembic upgrade <current>:heads --sql`, unescape `%%` -> `%`,
review, and apply the SQL (it updates `alembic_version` too).

**Parallel migrations (`heads`, not `head`).** Several feature PRs can each add a
migration while waiting for their SQL to be applied (Razorpay and messages did). Each
starts from the newest revision on `main`, so the history can have more than one
head, and everything runs `alembic upgrade heads`. `alembic_version` then holds one
row per head. Render from what the database actually has: the first branch applied
updates the row (`UPDATE ... WHERE version_num = '<parent>'`), and a second branch
from the same parent inserts its own (`INSERT INTO alembic_version ...`). Rendering
`<current>:heads` picks the right one. Two branches must not change the same table;
when they would, chain the later one instead. `alembic merge heads` can tie them
together later; it is not needed to run.

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

### Demo data

**Actions → Reset staging demo data → Run workflow**, typing `RESET STAGING`, replaces staging's data with four weeks of a busy tea and juice shop ending at the moment it runs. Run it again any time to bring the data up to today.

What it makes (all invented, names and numbers placeholders):
- **Menu:** 20 items in Tea, Coffee, Juice and Snacks, with recipes, two decoctions made in batches, fresh-fruit juices by yield, and six options (Less sugar, Large, Extra ginger, ...). 24 ingredients with pack sizes and reorder levels.
- **Sales:** about 5,000 bills on two counters, with morning and evening peaks, more on weekends, juices in the afternoon. Cash, UPI, card, split and khata; a few discounts with reasons, a void most days.
- **Tables:** 13 tables in three areas; waiter-phone orders with KOTs in one or two rounds. Right now: tables eating, one with its bill printed, takeaways in the kitchen.
- **Money:** a drawer shift per counter (a change of cashier at 3 pm), pay-outs, counts that are mostly right, sometimes ₹10-50 short or a little over. Ten khata customers, some paying back.
- **Stock:** opening counts, milk and bakery every morning, fruit three times a week, dry goods and cups by purchase order, a local-shop top-up when something runs low; wastage; a blind count every night, approved by the owner the next morning. **Yesterday's count is left for the owner to approve.**
- **Staff:** Ravi, Priya and Arun (waiter) are added. They must set a password: give each one a temporary password in **Staff** first.

**Kept:** the shop and every existing login and password. The shop is renamed *Jamun Tea & Juice (demo)*, regular GST with a synthetic GSTIN, cash shifts on (Shop & GST changes it back). Its email settings are not touched. **Deleted:** everything else, including the tablets. Each phone or tablet that used staging must **clear the site's data** (browser settings) and be set up again, or it keeps trying to sync bills from tablets that no longer exist.

**Setup, once:** add the repository secret `STAGING_DATABASE_URL` with Supabase's *Session pooler* connection string (`postgresql://...`, port 5432). The owner types it in GitHub; it is not in the repo or the code.

#### Decisions and trade-offs
- **Made through the real API, with the clock moved.** `scripts/demo_data.py` runs the app in-process and uses `time-machine` to step through each day, so every bill, KOT, shift, count and stock movement passes the same checks and services as the tablets: GST per line, deductions by recipe version, the append-only ledger, variance. Writing rows directly would be faster to build and easy to get subtly wrong (a bill whose stock never moved, a drawer that cannot balance). `tests/test_demo_data.py` runs two days of it in CI, so an API change that breaks it fails there, not on the button.
- **Built on the runner, loaded in one transaction.** The data is built in a throwaway Postgres on the GitHub runner (two minutes) and copied with `pg_dump`/`psql`: about 15 MB of rows, one round trip per 500. Building straight into Supabase would take thousands of queries from the US to Seoul. `scripts/demo/reset.sh` wipes and loads with `--single-transaction`, so staging gets all of it or none of it.
- **It checks before it deletes:** the target's migrations must match the code (`alembic_version`), and there must be exactly one shop.
- **The ledger is cleared with `TRUNCATE`.** Its triggers forbid row `UPDATE` and `DELETE`, which is the rule for the app. Resetting a staging database is not a correction to stock, so the wipe is a separate, explicit step, and the triggers stay as they are.
- **No session settings reach the pooler.** `pg_dump` output starts with `SET search_path = ''` and timeouts. On a pooled connection they could outlast the load and reach the app's next queries, so they are removed (the dump is schema-qualified).
- **No email or iMessage is sent.** The email and message outboxes are not copied, and settings that send email are left as the owner set them. A reset never mails 5,000 bills.
- **Not for production.** It deletes a shop's sales. The workflow runs only by hand, only with the typed confirmation, and only against the secret's database.

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

## Phase 3f: voids and the daily sales report

**Manage → Sales** (now the first Manage tab) shows one day from all tablets:
- the total and payment split
- item-wise quantity and ₹, sales by hour, and sales by staff (when more than one person billed)
- GST by rate (regular-GST shops)
- voided bills and their reasons
- bills where a tablet's total disagreed with the server's

Tap a bill to see it and, as owner, void it. Tablets show voided bills on their Today screen when online.

### Decisions and trade-offs
- **Owner only, enforced on the server.** If a cashier could void, they could keep a cash payment and erase its bill: the most common POS fraud. A cashier who made a mistake tells the owner.
- **The bill is never edited or deleted.** A `bill_voids` row records the reason, the note, who did it and when. The bill's `status` flag turns to `void` in the same transaction. The invoice number stays used: GST wants an unbroken series, and a cancelled invoice is kept as cancelled.
- **Stock comes back by mirroring that bill's own `sale` rows** (ledger reason `void`, same business date). Large and Less sugar come back exactly as they went out, even if the recipe changed since. The exception is "the drink was already made": then nothing comes back, because those ingredients really were used.
- **Day end treats a void as un-selling.** `movements()` nets `void` rows against `sold`, so a cancelled order does not raise the expected usage the count is judged against.
- **No voids once the day is approved.** Approval froze that day's expected stock and variance. A later void would put stock back into a day whose shelf was already counted, and quietly unbalance it. Correcting a closed day needs a credit note, which is later work. Void and approval take the same per-day advisory lock (`lock_day`), so a void lands wholly before the approval freeze or is refused after it.
- **Voids need internet.** Only the server can tell whether the day is still open. Billing itself stays offline-first.
- **Reports use printed totals.** The invoice is the legal record and what the customer paid. Bills where the server's arithmetic differed are listed, not silently corrected.
- The daily email leaves voided bills out of its totals and says how many there were. The weekly `bills.csv` gains `status` and `void_reason` columns.

## Phase 3g: staff accounts

**Manage → Staff** is where the owner adds people, resets passwords and switches people off:
- Each person logs in with their own mobile number and password.
- New staff get a first password the owner reads out (for example `ginger4821`), shown once. They must choose their own at first login.
- Anyone can change their own password by tapping their name in the top bar.

### Decisions and trade-offs
- **The server enforces "set your own password".** While `must_change_password` is set, every route refuses with `password_change_required`, except `/auth/me` and `/auth/password`. The owner knows that first password, so until it is replaced, anything done with it could have been done by the owner. "Who voided this" and "who sold this" would mean nothing.
- **A reset or a switch-off takes effect at once.** Both revoke every refresh token. A switched-off person fails the per-request `is_active` check, and a reset person fails the `must_change_password` check. An access token that is still unexpired is therefore useless too.
- **Changing your own password ends your other sessions** and returns fresh tokens to the device that made the change. A stolen phone loses access as soon as you change it from another device.
- **Lockout: 5 wrong passwords lock the account for 15 minutes.** The owner's reset clears it. The lock is short on purpose: anyone who knows a cashier's number can trigger it, and a long lock would let them keep that person out of the till. The lock message also reveals that the number has an account. I accepted that, because people's phone numbers are not secret in a shop.
- **Password rules are minimal on purpose:** at least 8 characters, not the phone number, and not one of the dozen most common passwords. The same rules run in `services/auth.password_problem` and `frontend/src/lib/staff.ts`. A breached-password check would need a list download or an outside service, which can come later.
- **Bills are credited to whoever rang them up.** The tablet records `cashier_id` at sale time. Before this, a bill was credited to whoever was logged in when it synced, so offline bills made by Ravi and sent after Arun logged in counted as Arun's. The server accepts only an id belonging to someone in this shop, including people since switched off. Anything else is credited to the person syncing. Bills from older app versions omit the key rather than sending null, so their retries still hash the same.
- **The tablet is still trusted for this.** The server cannot check who held the tablet offline. A cashier on a tampered tablet could credit a sale to a colleague, but not to anyone outside the shop.
- **Whoever logs in starts on New bill,** not on the screen the previous person left open.
- **Not done yet:** a quick PIN switch between cashiers on one tablet, and owner-defined roles (for example a manager who can do counts but not change prices).

## Phase 3h: shifts and the cash drawer

**On each tablet:**
- The first bill of a shift asks for the cash in the drawer. That amount is the opening float, pre-filled with the last count.
- **Today → Cash drawer** records money paid out (milkman, owner took cash) or paid in.
- **End shift** is a blind count by notes and coins.

**For the owner:** **Manage → Sales → Cash drawer** shows each shift:
- the float, cash sales and paid in/out
- what should be in the drawer, what was counted, and whether it matched or was over or short

The daily email lists one line per shift. **Shop & GST → Cash drawer** switches shifts off for a shop with no counter cash.

### Decisions and trade-offs
- **A shift belongs to a tablet,** because each tablet has its own drawer. Several people may bill into one shift (the owner helping at rush hour). Each bill still records who rang it up. The drawer's accountability sits with whoever opened the shift and whoever counted it. When someone else's shift is open, the bill screen says so, and **End shift** records the count under the person counting.
- **Shifts are made on the tablet, offline if need be,** and sent through their own outbox before the bills. They are idempotent by an id made on the tablet, like bills. Bills carry `shift_id`. The drawer is therefore checked against exactly the bills of that shift, not against a time window, which a wrong tablet clock would break. A bill whose shift was refused is still accepted and shows as "cash outside any shift".
- **The count is blind.** The person counting sees the total they counted, never the expected amount, so the count cannot be "made to match". This is the same principle as the stock count.
- **Expected = float + cash bills + paid in − paid out.** Voided cash bills are left out and listed beside it. Whether that money went back to the customer is something only the owner can judge.
- **Shifts block nothing.** A bill with no open shift asks for the float once and then saves. An unended shift shows as "Not ended" for the owner; the app never prevents billing because of it.
- **A cleared tablet picks up its open shift from the server** (`sync-state`), so it does not start a second shift over the first. It never re-opens a shift that it ended but hasn't yet sent.
- **Not done yet:** owner approval of a shortage, and a cash handover between two named people where the second confirms the first's count.

## Phase 4a: bill safety (no lost bills)

Phase 4's gate is "7 days live, no lost bills", so a lost bill must be visible.

**Manage → Tablets** shows, per tablet:
- when it was last seen, and its app build
- bills still waiting to send, and since when (flagged after 2 hours)
- bills the server refused
- **printed invoice numbers that never reached the server**
- whether its browser storage is protected

The daily email warns about any of these.

### Decisions and trade-offs
- **Only the tablet knows what it printed.** The server cannot see a bill it never received. After each sync the tablet reports what it holds (`POST /devices/{id}/report`), even if the sync failed, because a stuck tablet is what the owner most needs to hear about:
  - the highest invoice number per financial year
  - the numbers of the bills it still holds, waiting or refused
  - the oldest waiting bill
  - its storage persistence and app build

  A number up to the reported highest that the server lacks, and the tablet no longer holds, is **lost**.
- **A wiped tablet never reprints a number.** Before this, a tablet whose browser data was cleared resumed numbering after the server's last bill. That re-issued the numbers of bills that were printed but never sent, giving two paper receipts the same invoice number. `sync-state` now resumes after the higher of the server's last bill and the tablet's last reported number. That reported number only ever goes up, so a wiped tablet reporting "0" cannot lower it. The lost numbers then show on the Tablets screen.
- **Reports are throttled:** sent when something changed, or every 5 minutes so "last seen" stays fresh. They never block or fail billing.
- **Limit:** a bill printed and wiped before the tablet ever had internet again cannot be detected by anything. The paper receipt is the only record. Installing the app to the home screen makes the browser far less likely to clear its storage; the screen says so for tablets where it is not protected.
- **CI's screenshot branch** now carries `vercel.json` files that switch deployments off. Each screenshot push used to create two failed deployments that counted against Vercel's daily limit.

## Phase 4b: printing

Each tablet chooses how its receipts reach paper: **Today → Printer**, or **Printer settings** on any receipt.
- **RawBT app:** recommended for Android with a Bluetooth printer.
- **Bluetooth LE, straight from the browser.**
- **The browser's print dialog:** for a PC with a USB printer.

Other settings: paper width (58 mm = 32 characters, 80 mm = 48), auto-print on save, and a **Test print**. Receipts opened from Today print with a "(Reprint)" mark.

### Decisions and trade-offs
- **ESC/POS, generated in the app.** `lib/escpos.ts` lays the receipt out in fixed columns and encodes it in the command language almost every thermal printer uses: reset, alignment, bold, double-size total, feed and cut. It shows the same GST content as the on-screen receipt. Byte-level unit tests pin the layout, for example `CGST @2.5%  Rs.0.48` on exactly 32 columns.
- **RawBT over direct Bluetooth.** Most cheap printers sold in India use classic Bluetooth (SPP), which no web page can reach. RawBT is a free Android app that takes the receipt as a `rawbt:base64,…` link and handles any paired printer, so it covers the most printers with the least setup. Direct Bluetooth LE needs no app, but only some printers have LE, and Chrome makes the person pick the printer again after each reload.
- **ASCII only.** Printers print from their built-in code page, so "₹" becomes "Rs." and other characters become "?". A menu in Tamil or Hindi would need the receipt sent as an image (raster). That is possible later, if the pilot shop needs it.
- **Browser print stays the default** until a tablet is set up, so nothing changes for a tablet nobody has configured.
- **Untested on real hardware from here.** The pilot visit (or any ESC/POS printer) is the check. Run **Test print** first: if the line of digits wraps, the paper width setting is wrong.

## Phase 5.1: tables and the running-order engine

**Manage → Floor:** the owner sets up dining areas (Hall, AC room, Outdoor) and their tables, with bulk add (for example "6 tables" → T1–T6). Tables reach every tablet in the catalogue, so table service works offline. The order screens come in 5.2. This part is the engine underneath them.

### Decisions and trade-offs
- **An order is a list of events, not a row that gets edited.** Several devices touch one table: a waiter's phone adds a round, the counter prints the bill, the kitchen marks items ready, any of them possibly offline. Each action is an append-only event: `open`, `kot`, `cancel`, `move`, `details`, `bill_printed`, `ready`, `settle` or `cancel_order`. Each has an id made on the device and goes through an outbox, sent after shift operations and before bills. The database refuses UPDATE and DELETE on `order_events`, like the stock ledger.
- **One set of rules, in two languages, pinned together.** The order's state (lines, KOTs, cancellations, status, "changed after bill") is computed from its events by `services/orders.reduce` on the server and `lib/orders.reduce` on the device. `shared/order_cases.json` holds hand-worked cases that both must reproduce exactly: out-of-order arrival, ties, time zones, changes after the bill, settled orders ignoring later events. Events are applied by device time, then id, so devices that synced the same events show the same state.
- **Adding never conflicts.** Two phones adding rounds to one table offline just produce two KOT events. A line sent twice is kept once. Cancelling takes at most what is left.
- **Changes after the bill are flagged.** A KOT or a cancellation after `bill_printed` sets `changed_after_bill` and puts the order back to "open". This is the restaurant-fraud signal (print the bill, take the money, then remove items) the owner's report will show in 5.3.
- **Settling makes an ordinary invoice.** The bill goes through the existing pipeline, so GST, numbering, stock deduction and voids are unchanged. It carries `order_id` and is priced at the prices the items were ordered at. A unique index allows one invoice per order, so a second tablet settling the same table is refused as `order_already_billed`.
- **Devices see each other through `/orders/live`.** It returns the open and billed orders with their events. A device adds its own unsent events and applies the same rules, so its screen never waits for the network. Polling, not a live connection: serverless functions cannot hold one open.
- **One bad event never stops a tablet (fixed after staging, 4 Oct).** Events are checked one by one. A malformed event is refused with the field that is wrong (`invalid_event:data.lines.0.qty`), and that reason is logged. The rest of the batch is stored. Before this, one event the server could not accept made it refuse the whole batch (422). The tablet then resent the same batch every few seconds, and because orders sync before bills, no bill left the tablet either. On staging, tablet C2 held 30 bills, and Razorpay could not start ("the bill has not reached the server"). Bills now go even when orders fail; the server already accepts a bill whose order it never received.
- **The bad event on staging was an option.** The catalogue sends an option's `scale_factor` as a JSON number, and the tablet copies it into the KOT unchanged. Bills took a decimal there, but orders accepted only text, so every table or takeaway order with an option (Less sugar, Large) was refused. Orders now take the same decimal as bills, stored as text. The browser test sends a real option on an order; before, it only used the line's note, which is why CI missed this.
- **The tablet health report keeps only invoice series.** The kitchen ticket count (`kot:<date>`) shares the tablet's counter store. It was sent along, and the server refused every report from that tablet, so the owner's Tablets screen never showed the stuck bills. The app now sends only `26-27`-style keys, and the server drops any other key instead of refusing.
- **A stylesheet guard.** The rebase of #20 merged two style blocks mid-rule and left three braces open, so the cash drawer, Tablets and printer styles stopped applying on staging. Behaviour tests cannot see that. `styles.test.ts` now fails on any unclosed or misplaced block.

## Phase 5.2: table service (Tables screen)

**Tables** appears in the top bar once the owner has set up tables. The floor shows each table as free (dashed), eating (green, with the running amount, minutes and guests) or bill printed (yellow), plus running takeaway and delivery orders. Tap a table, tap items, **Send to kitchen**: a KOT prints and the phone goes back to the floor. More rounds the same way. **Print bill** prints the bill for the table; **Settle** takes the payment mode and makes the tax invoice. Also: cancel a sent item (reason required; a cancel ticket goes to the kitchen), cancel a whole order, move to a free table, guests and customer details, a kitchen note per item.

### Decisions and trade-offs
- **An order exists only once its first KOT is sent.** Tapping a table and walking away leaves it free; nothing to clean up, nothing on the owner's report.
- **The bill at the table has no invoice number; the invoice is made on payment.** Invoice numbers must run without gaps, and a table that adds a dessert after seeing its bill would otherwise burn one (or need a void). The paper bill says "Please pay at the counter"; the receipt printed on settling is the tax invoice. The trade-off: a customer who keeps the first paper has a bill, not an invoice, so the settle receipt is always printed.
- **Prices are frozen per line when the round is sent.** A menu change during a meal does not change what the table pays. The invoice uses the GST rules and rounding of a counter bill (`priceLines`), so the floor amount, the bill at the table and the invoice always agree.
- **Changes after the bill are allowed but visible.** Adding or cancelling after **Print bill** reopens the order and tells staff to print again; a cancellation always needs a reason. The event history keeps who did what and when for the owner's report (5.3). Adding a round has no reason field on purpose: a second chai is not suspicious, removing one is.
- **Kitchen tickets are on by default, per tablet.** Printer settings have "Print a kitchen ticket (KOT)"; switch it off where the kitchen has its own screen (5.3). The ticket on screen is built from the same rows as the paper, so staff see exactly what the kitchen gets. No prices on it.
- **Five-second polling while the floor is on screen.** That is a sync run every 5 s per open phone (well within the free tier for a pilot). A busy restaurant with many phones would justify a push channel later; not before.
- **Not in this step:** merging two tables into one bill and splitting a bill (Phase 6, with split payments and discounts), a kitchen display (5.3), table reservations.

## Phase 5.3: kitchen screen and the owner's table-service report

**Tables → Kitchen** shows every kitchen ticket (KOT) still to be made, oldest first: table or takeaway name, minutes waiting (red after 15), each item with its options and kitchen note. Tap an item when it is ready, or **All ready** for the whole ticket. Waiters see "Ready" next to the item on the order. A tablet left on the kitchen view stays there after a reload.

**Manage → Sales → Table service** (owner only) shows, for the day: orders by type, items cancelled after they were sent to the kitchen (value, reason, who, when, and whether it was after the bill), bills changed after printing, whole orders cancelled, and orders never settled. The same lines go into the daily email under "Table service".

### Decisions and trade-offs
- **"Ready" is just another order event.** The kitchen sends `ready` with the line ids through the same outbox as everything else, so it works offline and reaches the waiters' phones on their next poll (5 s). No new table, no new endpoint for the kitchen.
- **The kitchen view is computed, not stored** (`lib/table.kitchenTickets`): a ticket is a KOT with lines that are neither cancelled nor ready. A cancelled item drops off the screen as well as printing a cancel ticket.
- **The report reads the order state the engine already keeps** (`cancellations`, `changed_after_bill`, `bill_prints`), so the owner sees exactly what the waiters' screens computed. Cancelled lines are valued at the price they were ordered at, options included. A whole cancelled order is valued at what was still on it, so nothing is counted twice.
- **Owner only, enforced on the server** (`/reports/service` is behind `require_owner`). The route is keyed by date, so its tenant test is an explicit cross-shop check in `test_orders.py`.
- **Known limit: pay-first takeaway.** An order leaves the kitchen view when it is settled, because settled orders leave the live list every device polls. A takeaway paid before it is cooked therefore relies on the paper KOT. Keeping settled orders on the kitchen screen means letting `ready` apply after `settle` in the shared order rules (both languages and `shared/order_cases.json`) and sending recently settled orders to devices; that is a follow-up, not part of this step.
- **Flaky sales spec, fixed in the app, not the test.** The sync badge could say "All bills sent" while a bill saved during a running sync was still waiting: the in-flight sync's last count of the outbox could be read just before the new bill was saved and answer just after it. Now a kick during a sync recounts at once, and only the most recently started count may update the badge. Two unit tests in `sync.test.ts` pin both halves; each fails without its fix.

## Phase 5.4: UI polish

- **One sheet for every dialog** (`app/Sheet.tsx`). There were three copies of the component and seven hand-written dialogs. Now there is one, so Escape, tap-outside, focus and the header look and behave the same everywhere.
- **Bug found on the way: typing in a sheet lost the cursor.** Each sheet re-focused itself whenever the screen behind it re-rendered, because callers pass a new `onClose` function each time. On Tables, which refreshes every 5 s, a waiter typing a cancel reason lost the box mid-word. The printer sheet also reloaded its saved settings, dropping unsaved choices. The sheet now focuses once when it opens and gives the focus back to the button that opened it when it closes. The tables e2e spec waits through a refresh with the box focused; it failed before the fix.
- **Loading and load failures look the same everywhere** (`app/Status.tsx`). A failed load shows the reason and a **Reload** button in place, instead of "Loading…" forever (Stock, Recipes) or an error with no way back except switching tabs. The stock e2e spec makes the first load fail and reloads.
- **One-tap save on phones.** With the bill closed, the bottom bar shows **Save · Cash** (or whichever payment mode is selected), so the commonest sale, one tea paid in cash, is two taps: the tile, then Save. The bill still opens for anything else (options, quantities, another payment mode). The button names the payment mode on purpose: a one-tap save must never record UPI money as cash without saying so. Tablets already show the whole bill, so they do not get the button.

### Not done (and why)
- **No visual redesign.** The screens already share one stylesheet and tokens; the pilot shop's feedback should drive the next round, not guesses.
- **Lint warnings** (`set-state-in-effect`) are left as they are: they flag the load-on-mount pattern every screen uses. Moving to a data-fetching library is a bigger change than it is worth before the pilot.

## Phase 9: UI and UX pass

### 9.1 Navigation
- **Phones: the screen tabs are a bar along the bottom.** A counter phone is used one-handed, and the top of a phone is the hardest place to reach. The top bar is now one row: shop and tablet, sync badge, Log out. The till and the table-order drawer sit on top of the tab bar (`--nav-h`), never under it. A shared e2e guard (`expectPhoneBars`) checks that the bar is pinned to the bottom in one row and the top bar stays one row; the phone top bar had broken twice before.
- **Manage's twelve sections are grouped:** Money (Sales, Reports, Khata), Stock (Stock, Purchases, Day end, Recipes), Setup (Shop & GST, Staff, Floor, Tablets, Messages). On a phone the groups wrap above the page; the old single row scrolled sideways and hid most sections. On a tablet they become a left sidebar, and Manage pages use the full width instead of a 760 px column.
- **Not changed:** section and tab names, so staff who know the app find everything where its name says.

### 9.2 Sales: one row per cash drawer
- **Each drawer is one row:** who, which tablet, when, what should be in it, and its state (*Not counted*, *Matched*, *₹20 short*). Tap it for the sums (float, cash sales, paid in/out, counted). On a busy day with nine tablets this section was most of a 3,500 px page on a phone.
- **A drawer that was counted and does not match opens by itself.** The owner should not have to hunt for the one that is short. Matched and still-open drawers stay folded.
- Uses the browser's own `<details>`: keyboard and screen readers work with no extra code.

### 9.3 Jamun & Berry look
- **One deep colour for the app, one bright colour for the main action.** Jamun (`--brand` `#3B1468`) is the top bar, chosen sections, counts and the folded till bar. Berry (`--accent` `#E23E72`) is kept for the one button that finishes the job on each screen (**Save and print**, **Send to kitchen**, **Log batch**). Green still means *done* (sent, matched), turmeric means *look at this* (not counted, reorder), chilli means *wrong* (short, below zero). The first try with a bright lime read as a toy; a dark base with one strong accent is the pattern quick-commerce apps use, and keeps the money and the main button the loudest things on the screen.
- **Plus Jakarta Sans, bundled** (`@fontsource`, weights 500/700/800; the browser fetches only the subsets a page uses, about 36 KB for English text). It has clear figures for ₹ amounts. Shipping it with the app keeps it offline and inside the app's security policy (no Google Fonts call).
- **Cards, not lines.** Tiles, stock rows and sections are white cards with a soft shadow on a pale lilac ground (`--steel`), 12/20 px corners. Secondary actions (Discount, + Customer, chosen options) are soft jamun pills, so they read as buttons without competing with Save.
- **Till:** on a phone the closed till is a jamun bar floating above the tab bar (count, total, open); open, it is a light sheet. On a tablet it is a white card beside the menu.
- **Icons on the phone tab bar** (inline SVG, `aria-hidden`; the tab's text is its name). Tablets keep the text pills in the top bar.
- **App icon and theme colour** follow the brand, so the installed PWA and the phone's status bar match.
- **Not changed:** layout of the money, wording, and every control's place. This is a look, not a relearn.

### 9.4 The rest of the screens
- **Every list row is a card:** Today's bills, open orders, tables, kitchen tickets, stock, staff, recipes, options, khata, purchase orders, messages, payments and invoice series. A white card with a soft shadow, no grey outline. A row that needs attention keeps its colour (turmeric for bill printed, chilli edge for a problem), so it still stands out.
- **Free tables are solid cards** instead of dashed outlines. Busy tables are still green and printed bills turmeric, so the floor reads at a glance.
- **Sent** on Today is a soft green pill, the same as *Matched* in Sales.
- Sheet headers centre the title and **Close** on one line.
- **Browser tests run with reduced motion,** which the app already honours by turning off its button colour fades. A screenshot taken right after a tap no longer catches a colour halfway (the Floor/Kitchen switch looked greyed out).

## Phase 6: discounts, split payment, customers and khata, split bill

**At the till:**
- **Discount** takes an amount (₹ or %) off one line or the whole bill. It always needs a reason (quick picks: Regular customer, Staff, Complaint, Offer). A cashier can take off up to the owner's limit (**Shop & GST → Discounts**, 10% by default); the owner has no limit.
- **Split** takes part in cash and the rest by UPI or card.
- **Credit** puts the bill on a customer's khata, optionally with part paid now in cash. **+ Customer** attaches a customer to any bill, for their visit history.
- Receipts show the discount on its own row, each payment part, and the customer's name (never their number).

**At the counter:** **Today → Customers** finds a customer by number or name and shows their visits and what they owe. **Take a repayment** records cash, UPI or card; this needs internet. Cash repaid goes into that drawer's expected cash.

**At a table:** **Settle → Split bill** puts each item on bill 1 to 4, with a payment mode per bill, and makes all the invoices at once.

**For the owner:** **Manage → Khata** lists everyone who owes, biggest first. **Manage → Sales** shows discounts with reasons (over-limit ones marked), credit given and repaid, and bills to look at. The daily email has the same lines.

### Decisions and trade-offs
- **A discount is on the invoice, so it lowers the GST.** A line discount comes off that line. A bill discount is shared across the lines in proportion to what is left on each, using largest remainder so the shares add up to the paise (ties go to the earlier line). Each line is then taxed on its own reduced amount, at its own rate. This is the usual reading of GST valuation (a discount shown on the invoice at the time of sale reduces the value). **Confirm with the shop's CA.** The rule is in `gst.py` and `gst.ts`, pinned by five hand-worked shared cases, three error cases, and 1,000 random discounted bills that TypeScript must reproduce from Python's answers. Receipts list items at full price, then the discount, so a customer can check the arithmetic.
- **Limits are enforced on the tablet and flagged on the server, never refused.** Refusing a bill the tablet already printed would lose a sale that happened. A cashier simply cannot go over the limit in the app. A bill that does anyway (an old app, a tampered tablet, a limit lowered while a tablet was offline) is saved with `discount_over_limit`. The other flags are `discount_without_reason`, `payment_parts_mismatch` and `credit_without_customer`. They live in a `flags` list on the bill, so the next rule needs no migration.
- **Older tablets are not disturbed.** An undiscounted, single-mode bill sends byte-for-byte what it sent before (a unit test), and the server leaves unused new keys out of the idempotency hash (a test compares with the old hash). A retry from a tablet that has not updated stays a harmless duplicate.
- **Split and credit are payment *parts*, not new kinds of bill.** `payment_parts` holds `[{mode, paise}]`, and `payment_mode` says `split` or `credit`. Reports, the cash drawer and the email count each part under its own mode, so a ₹15 cash + ₹20 UPI bill expects ₹15 in the drawer.
- **What a customer owes is computed, never stored.** It is the credit parts of their bills that are not void, minus repayments. A voided credit bill stops being owed by itself, with no balance to correct. Repaying more than is owed is refused, and the same repayment sent twice is recorded once (its id is made on the tablet).
- **Customers are made on the tablet, offline; the server keeps one per number.** Two tablets that each made "Priya" for the same number end up on one khata. A newer name replaces an older one. A changed number is a new customer. The number is personal data: it is stored on the customer and shown to staff (they call the customer), but never printed or written to messages or logs.
- **Repayments need internet; credit sales do not.** A sale must never wait for the network. A repayment needs the true balance, which only the server has.
- **Split bill makes every invoice at once.** One part now and the rest later would leave a half-paid table whose plan exists only on one phone. Each part is a normal invoice with `order_part`. The unique index is now `(order_id, order_part)`, under the old name, so the "order already billed" check still works. The order is settled when every part is (`settle` carries `part`/`parts` in both reducers, with shared cases). Each part rounds to the rupee on its own, so the parts can differ from the whole by a few paise each.
- **`payment_mode` gains `split` and `credit`.** Postgres cannot drop enum values, so a downgrade leaves them on the type. Nothing older uses them, and upgrading again skips them.
- **Not done:** discounts at the table (a table discount can be given at the counter for now), splitting a bill equally by amount (an invoice must list items, and an equal split is a payment split, which **Split** does), credit limits per customer, and reminders to customers who owe.

## Phase 7: reports and inventory

**Manage → Reports** (owner):
- **Sales over time:** any range up to 92 days, with quick picks (last 7 days, this week, this month, last month). Shows totals, payment modes, a bar per day, items sold and a bar per hour of the day. Days and items download as CSV.
- **GST for a month,** in the shape of GSTR-1:
  - B2C (small) by rate;
  - HSN summary;
  - invoices issued per tablet series: from, to, cancelled, issued, and any numbers that never reached the server.

  Each table downloads as a CSV for the accountant.
- **Stock value:** what is on the shelf at the latest purchase price, with a CSV.

**Manage → Purchases** (owner):
- **Suppliers.**
- **Purchase orders.** **Fill from reorder levels** proposes everything below its level. **Receive into stock** records what actually came and what it cost, and enters it as stock.

**Stock → an item → Reorder below** sets the level. Stock marks items under it.

### Decisions and trade-offs
- **Reports are computed when asked, not stored.** A quarter of a busy tea shop is a few tens of thousands of bills: well within one query. Pre-computed totals would need keeping in step with voids and late bills, and would be one more thing that can disagree with the invoices. The 92-day limit keeps every request quick on a serverless function.
- **All sales are B2C (small) and intra-state.** Customers of a tea shop are unregistered and local, so every sale is CGST + SGST, with the place of supply being the shop's state. Nil-rated (0%) sales are a separate total, not a rate row. A shop that sells to registered businesses (B2B invoices with the buyer's GSTIN) would need more; that is not built. Composition and unregistered shops see the totals with a note that GSTR-1 is not their return.
- **HSN codes come from each item as it is today.** Bills did not keep a copy of the code. Changing an item's code changes how past sales are grouped in the summary; the screen says so. Snapshotting the code on each bill line is the fix, if this ever matters.
- **Invoice series count numbers, not rows.** "Total" is the span from the first to the last number. "Not on the server" is the gap. That is the lost-bill signal from Tablets, shown again where the accountant will see it.
- **CSV files are made in the browser** from the report already on screen. No second endpoint means no download link that needs the login token in a URL. Files have a BOM so Excel shows names correctly, and amounts in plain rupees (`19.04`) so they sum in a spreadsheet.
- **Stock value uses the latest purchase price,** the same cost the day-end variance uses (a batch item: its ingredients' cost per batch). It is not FIFO or weighted average. For a tea shop, stock turns over within days and the difference is small; the owner gets one consistent number. Negative stock counts as worth nothing and is listed so it gets fixed.
- **Receiving an order is an ordinary stock-in.** The ledger stays the one place stock moves. The purchase price updates as for a stock-in typed by hand. Each order line links to the receipt it made. What came can be less than, or different from, what was ordered; the order keeps both. An order is received once. Anything that comes later is a normal stock-in.
- **"Fill from reorder levels" orders up to twice the level.** It is predictable and easy to explain, and the owner edits the quantities before saving. A forecast from past usage would be smarter, but harder to trust.
- **Owner only,** like stock-in: buying for the shop and entering stock are the owner's.
- **Not done:** sending the order to the supplier (WhatsApp or SMS comes with Phase 8b's providers), supplier bills and payments owed to suppliers, and stock valuation on a past date.

## Phase 8c (design only): Swiggy/Zomato, and more than one outlet

Not built: the owner has no partner accounts yet. What it would take, so the decisions are on paper.

**Swiggy and Zomato orders**
- **How orders arrive.** Both platforms send orders to a restaurant's POS only through approved integration partners (or their own partner APIs, with onboarding), not through a public API. Plan on a partner aggregator, or the platform's own POS integration once the shop is approved. Either way: a webhook to the API with a signature to verify, then an acknowledgement within the platform's time limit.
- **Where they go.** An aggregator order becomes a running order of type `delivery`, with its platform and platform order id (unique per shop, which makes the webhook idempotent). It is posted as `open` + `kot` events from a "platform" device, so it shows on the Tables screen and the kitchen view like any other order, prints a KOT, and settles into an ordinary invoice. Status updates (accepted, ready, picked up) go back to the platform from the existing `ready` and `settle` events, through an outbox like email.
- **Money.** The platform collects the payment, so the invoice's payment mode would be the platform (a new payment part, `swiggy` or `zomato`), and the platform's commission and payouts are reconciled separately against its settlement report. On food sold through an e-commerce operator, the **operator** pays the GST under section 9(5) (restaurant services, since 2022). Those invoices must be marked so the shop does not report that tax again in its own GSTR-1. Confirm with the CA before building.
- **Menu sync.** Prices often differ on the apps (to cover commission). Keep a per-platform price on the menu item rather than a separate menu, and push changes through the partner API.

**More than one outlet**
- **Today, a shop is the tenant**: every table carries `shop_id` and the tenancy layer filters by it. The smallest change that works is a `business` above shops: one login, a picker, owner reports across shops, and the shop still the unit of stock, invoice series, GST registration and day end.
- **What changes.**
  - A user can belong to several shops (a membership table), and the token names the shop chosen at login.
  - Owner reports gain a "business" view that reads several shops in one system-flagged session.
  - The menu can be shared (copied per shop, so each outlet's prices and recipes can still differ).
  - Stock moves between outlets as a transfer: an `out` row in one shop's ledger and an `in` row in the other's, linked.
- **What does not change:** each outlet keeps its own invoice series and, if registered separately, its own GSTIN; tenant isolation still holds per shop. The tenant gate and RLS tests extend to "a user of shop A can see shop B only if a member of both".
- **Cost:** most of the work is the membership and shop-switch plumbing and the cross-shop reports. The billing, stock and order engines stay as they are.

## Phase 8a: online payments through Razorpay (test mode)

**On the till:** pick UPI or Card, tick **Collect through Razorpay**, and tap **Save and collect**. The bill is saved as usual. The till sends it to the server, asks Razorpay for an order for the bill's total, and shows **Open payment page**. The customer pays on that page. The till watches the server and shows **Paid** when the money has arrived, then prints the receipt. If anything fails, **Took the payment another way** prints the receipt anyway.

**For the owner:** **Manage → Sales → Online payments** lists each bill collected online with its Razorpay payment id. It flags *Not paid online*, *Paid a different amount*, and *Paid, then voided: refund due*.

**Server settings (Vercel env, API project):** `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (test-mode keys), and `RAZORPAY_WEBHOOK_SECRET` (the secret you type when creating the webhook in Razorpay's dashboard). Without the key id and secret, the option does not appear on the till. The webhook URL is `https://chai-pos-api.vercel.app/api/v1/payments/razorpay/webhook`, with events `payment.authorized`, `payment.captured`, `payment.failed` and `order.paid`.

### Decisions and trade-offs
- **Checkout runs on a page served by the API, not inside the app.** The app's security policy allows no third-party script. That policy is what makes keeping the refresh token in the browser acceptable: a script that can run in the app can read it. Razorpay's `checkout.js` is a third-party script, so it runs on `GET /payments/razorpay/checkout`, on the API's address, where no token is stored. The app opens that page in a new tab and polls `GET /payments/razorpay/status`. The cost: a tab switch for the cashier, and the page needs internet to load Razorpay. The alternative (letting Razorpay's script into the app) would make every Razorpay script update a path to every shop's login.
- **The bill comes first; the payment is a separate record.** The invoice is saved, numbered and printable on the tablet before any payment is attempted, as with every bill. The `payments` table (RLS on, tenant-scoped) links to it. A payment never changes a bill. A different amount, a bill left unpaid, or a paid bill that was later voided is flagged for the owner, the same way device-versus-server totals are.
- **Only a signature marks a bill paid.** Checkout's result is checked with HMAC-SHA256 of `order_id|payment_id` under the key secret. The webhook is checked with HMAC-SHA256 of the raw body under its own secret. Both comparisons are constant-time. The "attempt failed" call from the page is unsigned, so it can only ever record a failure, never a payment, and a later success still wins.
- **Idempotent.** One row per Razorpay order (unique order id), one Razorpay payment per row (unique payment id). Asking for an order twice reuses it. A webhook delivered twice, or verify called twice, changes nothing. Paid is final; a late failure of an earlier attempt does not undo it.
- **Webhook events for orders this server never made are acknowledged and ignored.** Razorpay retries anything that is not a 2xx, and one Razorpay account may serve other apps.
- **Payment mode stays `upi` or `card` on the bill.** No new Postgres enum value: "online" is the existence of a payment row. Plain strings with check constraints in `payments` keep later providers a one-line change.
- **The cashier's method comes first, and the other is the way out.** Checkout shows a block for the method the cashier picked, then a block for the other one (UPI or card), and nothing else. The first version used `prefill.method`, which Razorpay ignores without the customer's phone and email, so "Card" opened the full Checkout. Later versions showed only the chosen method; when the Razorpay account could not offer it on that device (UPI in a desktop browser: intent needs a phone, collect is retired, QR must be switched on), the customer was stuck at "No appropriate payment method found". Razorpay skips a block it cannot show, so the other method is always there. The cost: a customer can pay a UPI bill by card. The server records the method Razorpay reports, and the owner's report flags it (*Paid by the other method*).
- **The server confirms with Razorpay and captures.** After the signature checks out, the server fetches the payment from Razorpay. It checks that the payment belongs to this order, captures it if it is only `authorized`, and records the amount Razorpay actually took. Without this, a Razorpay account set to capture manually would leave payments authorized, and Razorpay refunds those after a few days. If Razorpay cannot be reached at that moment, the signature (which only Razorpay can make) is enough to show the bill paid, and the webhook (`payment.authorized`, `payment.captured`, `payment.failed`, `order.paid`) confirms it later. A capture that fails inside the webhook answers 503, so Razorpay sends it again.
- **Keys are read without stray spaces or newlines** (a common paste mistake that makes Razorpay refuse every call). **Shop & GST → Online payments (Razorpay) → Check connection** shows whether the keys are set, test or live, accepted by Razorpay, and whether the webhook secret is set. It never shows a key.
- **Tests never call Razorpay.** `services/payments.set_client` swaps the HTTP call for a recorder; signatures are computed with test secrets in the tests. The browser test answers the three payment calls itself, because CI has no keys.
- **Not done yet:** refunds from the app (the owner refunds in Razorpay's dashboard; the report says when one is due), collecting online for a bill from Today after the fact, and live mode (switching keys is all it needs, after a real-money test).
- **Unverified from here:** the checkout page against Razorpay itself. This environment cannot reach Razorpay, so the first real test-mode payment is the check (see HANDOFF).

## Phase 8b: customer messages by iMessage (Inkbox)

**Taking a number:** the takeaway/delivery sheet and the order's **Customer** sheet show, once a 10-digit number is typed, *Customer agrees to get the receipt and "order ready" on this number by iMessage*. It is off by default.

**What is sent, only to customers who agreed:**
- **Order ready** (takeaway), when the kitchen has marked everything left on the order ready.
- **Receipt link**, when a settled order's invoice reaches the server. The link opens the customer's copy of the bill without logging in.

**For the owner:** **Manage → Messages** lists every message with the number masked (`••••••3210`), its status and any error. **Send waiting now** retries; every sync and the daily cron retry too.

**Server settings (Vercel env, API project):** `INKBOX_API_KEY` (secret) turns sending on. `INKBOX_IDENTITY_ID` is needed only with an organisation-wide key, to name the sender. `PUBLIC_API_URL` defaults to the staging API, where receipt links point. Without a key, messages are written to the outbox and marked *Not sent (no provider)*; nothing leaves the server.

### Decisions and trade-offs
- **Inkbox has an app-side API** (`POST https://inkbox.ai/api/v1/imessage/messages`, `X-API-Key`, `Idempotency-Key`). I read its shape from Inkbox's published SDK, because its docs site is blocked from this environment. The catch is **Inkbox's shared iMessage service only lets you message people who messaged you first**. A customer who has never texted the shop's Inkbox identity gets a refusal, which shows as *Failed* with the reason. Messaging new customers needs a **dedicated Inkbox line**, which is an account decision for the owner (see HANDOFF). The code works the same either way.
- **Consent is per number, on the order.** `message_ok` lives in the order's event history next to the number, in both reducers, pinned by `shared/order_cases.json`. Changing the number without a fresh "yes" switches consent off, on the server and on the device, so a mistyped number that gets corrected is not messaged on the old consent. Dine-in customers can also agree, for the receipt.
- **Phone numbers are not copied anywhere.** The `messages` outbox has no phone column (a test checks the table). The number is read from the order at the moment of sending, so a number corrected before sending is used and nothing else keeps it. Errors are scrubbed of anything that looks like a number before they are stored or shown. The owner's screen masks numbers. Nothing logs them.
- **Same outbox pattern as email.** A message is a row written in the same transaction as its event, delivered after, never raising into billing or orders. It is retried up to 5 times, and it is exactly-once per shop by its key (`ready:<order>`, `receipt:<bill>`), which is also sent to Inkbox as the idempotency key.
- **The receipt link is signed, not stored.** The token is the bill id plus an HMAC of it, using a key derived from `JWT_SECRET`. It needs no table, and ids cannot be guessed or walked. The page shows the bill as printed (GSTIN, lines, GST, total, payment mode; "VOIDED" if voided) and never the customer's number. It sends `noindex`, `no-store` and a strict CSP. Rotating `JWT_SECRET` invalidates old links, which is acceptable for receipts.
- **Not done:** SMS and WhatsApp (the same `Transport` slot; the owner wants them later), messages for counter bills (they carry no customer number), and a customer opt-out reply ("STOP"). For now the owner can untick consent on the order.

# Chai POS

Billing and stock-accuracy app for tea and juice shops: GST bills that work
offline, SOP-based stock deduction, and a day-end report of what went missing.

Spec and phase gates: [docs/SPEC.md](docs/SPEC.md)

## Run it locally

Everything on your own computer: a local Postgres, the API and the app. Nothing
touches staging (Supabase or Vercel), so try things here first and push only
what works. Needs Docker Desktop and git.

```bash
git clone https://github.com/Beniljenish/chai-pos.git && cd chai-pos   # once
./local.sh      # database + API (:8000) + app, demo data the first time, then open http://localhost:5173
```

`./local.sh` is the two steps below in one. By hand:

```bash
docker compose up --build          # database + API (:8000) + app (http://localhost:5173)
```

In a second terminal, the first time only, fill the database with four weeks of
demo data. Pick any password of 8+ characters; it becomes every demo login's
(you will not need it in local test mode, see below, but it is the real one if you
switch test mode off):

```bash
docker compose exec -e DEMO_PASSWORD=<your password> api python -m scripts.local_demo
```

Then open http://localhost:5173 and log in as the owner `9000000000` (cashiers:
`9000020001`, `9000020002`). Edits to `backend/app` and `frontend/src` reload
by themselves. A new migration: `docker compose restart api` applies it.

- Look at the database: any Postgres tool (TablePlus, DBeaver, pgAdmin) on
  `localhost:5433`, database `chai_pos`, user and password `chai`.
- **Local test mode (no password).** Docker Compose runs the API with `DEV_LOGIN=true`: the login screen shows "Local test mode" and only asks for the mobile number. The API refuses to start with this on unless its database is on this computer (localhost, 127.0.0.1 or the compose `db`), and never with `ENV=prod`, so the setting cannot be copied onto Supabase by accident. To test real passwords, remove that line from `docker-compose.yml`. Staff set their own passwords at go-live (the owner sets a temporary one, they change it on first login: README, "Phase 3g: staff accounts").
- **Food courts and outlets** are made by the **super admin**: open `http://localhost:5173/admin` and sign in with `9000000099` (no password in local test mode). Create a food court, then **Add outlet**: a brand-new outlet (a shop and its owner's login; tick the sample menu to try ordering), or an existing shop by its owner's number. Then sign in as that outlet's owner in a private window (a browser holds one login at a time) and switch on Manage → Food court → Taking online orders. `./new-outlet.sh` makes an outlet's shop and login from the terminal instead, and the admin page then attaches it.
- Forgot the demo password: `./reset-password.sh` asks for a new one and keeps your data.
- Start again from empty: `docker compose down -v` (deletes the local data only).
- Stop: Ctrl+C, or `docker compose down` (keeps the data).
- Get the latest code: `git pull`, then `docker compose up --build`.

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

### 9.5 Login screen and a tidier Manage
- **Login is the shop's front door:** jamun background, the app name and three lines on what it does, and a glass of chai that fills, steams and floats. The form slides in beside it on a tablet, below it on a phone. It is all CSS and one inline SVG: no animation library, nothing to download, so it works offline like the rest of the app. With *reduce motion* on, it is a still picture (and so are the CI screenshots).
- **Manage's sections have icons and sit in one card.** On a phone, each group is one row of icon tiles (five across, so Setup's five fit at 360 px). Every section is still one tap from every other, nothing scrolls sideways, and nothing hides in a menu. On a tablet the sidebar is a sticky card from the top of the page with the current section filled in jamun. The names did not change, so tests and staff find them as before.
- **Small polish:** a hairline border colour for cards (`--line`), a lighter two-layer shadow, a soft focus ring on inputs, hover states for a mouse, a gradient top bar with the app icon (tablets only: the phone top bar must stay one row).
- Icons live in one place (`src/app/icons.tsx`), shared by the tab bar and Manage.

### 9.6 Taptallow, and movement
- **The app is called Taptallow** (the domain is taptallow.tech): browser title, installed app name, login, report emails and the API title. The repository, the Vercel projects and every internal key stay `chai-pos`. In particular the tablet's bill store is still the IndexedDB database `chai-pos`: renaming it would open an empty one and strand any bill not yet sent.
- **Small, quick movement that says what happened,** each under a quarter of a second so the counter never waits: a screen fades up when it opens; a sheet slides up (phone) or zooms in (tablet) over a blurred page; a menu tile lifts under a mouse and presses in under a finger; the count on a tile pops. Everything is CSS, and the existing reduced-motion rule turns it all off (so do the browser tests).
- **Loading shows shimmering rows** where the content will be, instead of a line of text. The words are still there for screen readers.
- **Phone tab bar is frosted glass** over the page. Page titles shrink a step on phones, and links beside a title (Customers, Printer) stay on one line.
- **Report emails** say *Sent by Taptallow*. The sender's name comes from `EMAIL_FROM` when it is set in Vercel, so the owner changes it there if it still says Chai POS.

### 9.7 Design A, from mockups the owner chose
Mockups of six screens went to Benil first. He chose the light till (a dark till was the alternative) and a restyle of every screen before any new feature.
- **Tablets (820 px and up) have a left rail:** the app icon, the four screens, then the sync state, shop and who is logged in, and Log out at the foot. The menu and till get the full height. Phones keep the bottom tab bar and a one-row top bar, now white with the app icon; Log out is an icon there (its name is unchanged for screen readers and tests).
- **Menu tiles** carry a two-letter badge in one of five soft colours (the same colour for the same item every day) and, for a registered shop, the item's GST rate. Both are `aria-hidden`: a tile is still named by the item. A tile already on the bill has a jamun ring.
- **The till** is the right-hand side of a tablet's screen, not a floating card. For a regular-GST shop it shows the taxable value and CGST + SGST above the total. The payment modes have icons, and the chosen one is soft jamun with a jamun edge, so Save stays the loudest thing. Save shows the amount (hidden from its name).
- **Today opens with four numbers:** sales, bills, the average bill, and bills waiting to send.
- **Manage on a tablet** has a white sidebar the height of the screen. A cashier's Stock page has no sidebar and stays one column (`.manage:has(> .subnav)`).
- **Every card has a hairline:** it is part of the shared `--shadow` token, so the look is one change, not forty.
- **Not in this round** (new features, each to be done on its own): searching the menu, sales by hour against last week, stock level bars and stock value, counts of things waiting on the Manage sidebar, a Counter/Takeaway switch on the till.

### 9.8 Mobile first: the phone flow, end to end
Benil asked for the phone to come first and chose all four parts from ten phone mockups. Tablets are unchanged.
- **Selling with one thumb.**
  - The login form sits at the bottom, under the brand.
  - A tile already on the bill shows **− 2**: one tap takes one off, without opening the bill. This works on tablets too; the button is named "Take one *item* off the bill".
  - The open bill is a sheet with a handle over a dimmed page. The closed bill bar has an up-arrow to say it opens.
- **"₹65 saved"** replaces the receipt pop-up on phones, right after Save. It shows a tick, the amount, the payment and the bill number, then the receipt, with Print again and New bill at the bottom. A reprint from Today still shows the plain receipt. It is the same dialog with the same buttons, so printing and the tests are unchanged.
- **Manage on a phone is a list, like the phone's Settings.** A section fills the screen with **‹ Manage** to go back. This replaces the tile grid that sat on top of every page.
  - *Trade-off:* Manage on a phone no longer opens straight on Sales. It opens on the list, with Sales as the first row, one tap away. Tablets still open on Sales, with the sidebar.
  - The browser tests reach a section through a shared helper (`openSection` in `e2e/helpers.ts`) that goes back to the list first when it needs to.
- **Today and Tables:**
  - Shift buttons are equal pills.
  - Floor and Kitchen are a segmented switch, and "+ Takeaway" and "+ Delivery" are soft pills.
  - Tables are three across on a phone.
- **The day-end count is guided**:
  - "3 of 7 counted" with a bar, which stays at the top while scrolling;
  - the item to count now is ringed and marked **Now**, and counted items turn green;
  - big + and − buttons;
  - a bar fixed above the tab bar with **Next item** (it scrolls to the next one not yet counted) and **Send count**.

  Every item stays on the page, unlike the mockup, which folded counted items away. A cashier can still scroll back and fix one, and nothing hides a control the count needs. It is still blind for cashiers: no expected amounts.

### 9.9 Four quick reads: menu search, against last week, Manage counts, stock bars
Benil chose these from a mockup. All four are in the app only: no new routes, no migration.
- **Menu search** on the till. It looks across every category at once, finds every word typed (in any order) in the item's name or category, and highlights the matching letters. While a search is typed the category chips are hidden, and clearing it brings them back.
- **This week against last** on Sales (`WeekCompare`, one `/reports/range` call). The chosen day sits beside the same weekday a week earlier, with ▲/▼ and a whole percent, and seven pairs of bars compare each of the last seven days with the week before.
  - *Trade-off:* **today shows no percentage.** A half-finished day against a full day last week reads as a crash (▼61% at lunchtime). Today says "Today so far" and shows last week's full day beside it. A like-for-like comparison by time of day is possible later, from the hourly split.
  - Money and bill counts are integer paise and whole bills; the percent is only for display.
- **Counts in Manage** (`useAttention`, owner only). Four small reads: stock, khata, pending wastage, and the day-end report for today and yesterday. A failed read counts as zero rather than hiding the rest. It refreshes when the tab changes, when the app regains focus, and every five minutes.
  - **Stock: "N low"** is below the reorder level or below zero. "Near the level" gets an amber bar but is not counted.
  - **Day end: "N to approve"** is pending wastage plus submitted counts.
  - **Khata: "N owe"**, not "overdue": the khata has no due dates, so "overdue" would claim something the app does not know.
  - Manage in the tab bar shows the total. The badge is read as a description, so the button's name stays "Stock", and the tests that find it by name still work.
- **Stock level bars.** Each ingredient with a reorder level shows how full it is, with a tick at the level. Pink is below it, amber is within a quarter above it, green is fine. The bar is scaled to twice the reorder level, so the tick always sits in the middle. Order: worst first, A–Z, or low only.
  - Without a reorder level there is no bar, just the quantity.
  - The bars are drawn from the numbers the server already sends. They are display only; the ledger's numbers are the ones that count.
  - *Left out of the mockup:* the "about half a day left" line under Milk. It would be a guess from the last week's sales, shown as if it were a fact.

### 9.10 Alerts, margin per item, and what the daily email now says
Chosen from a mockup. No migration: every number is worked out from records the app already keeps, so there is nothing new to store or to get out of step.
- **Alerts** (Manage → Alerts, `services/alerts.py`, `GET /reports/alerts`). The rules are fixed and plain, so each alert can be explained in a sentence:
  - **Drawer short**: a closed shift counted ₹20 or more under what the bills say (over by ₹100 or more is "take a look").
  - **Void burst**: 3 or more voids by one person within an hour.
  - **Discounts above the usual**: more than ₹50 in a day and 3 times the last 14 days' daily average.
  - **Large wastage waiting** for approval.
  - **Price up**: an ingredient's latest purchase cost 5% or more above the purchase before it. News, not a warning.
  - **Over the recipe**: used 10% or more over the recipe across at least 3 closed days.
  - *Trade-off:* the thresholds are constants in one file, not settings. A shop with very different numbers (a ₹5 tea at huge volume) will want them changed, and that is a better conversation after the pilot week than a settings screen now.
  - *Not built:* a rule has to be explainable from the records. "Sugar over the recipe for 3 days" is; "this cashier seems suspicious" is not.
- **Margin** (Manage → Margin, `services/margin.py`, `GET /reports/margin`). Cost is the item's current recipe times the latest price paid for each ingredient (`cost_per_unit_paise`, set on each stock-in). A made-here ingredient (decoction) costs its inputs over the batch's yield. Revenue is the price without GST, using the shared GST code.
  - **An item with an unpriced ingredient gets no margin**, and says which one. Showing "100% kept" because milk's price was never entered would be a lie.
  - The standard serving only: size and add-on options are not included.
  - Colours: under 50% kept is pink, up to 67% amber, above green. A guess to be set from the pilot shop's real numbers.
- **The daily email** (`reports.enqueue_daily`) gains three sections: **Needs you** (the alerts above, except price news), **Stock to reorder** (the same list as Purchases suggests) and **Prices**. It is the existing morning email (7 am IST, from the Vercel cron), not a second one, so there is nothing new to switch on.
  - *Not built:* WhatsApp. It needs a paid business account and approved message templates, and those are keys and approvals the owner must set up himself. The email carries the same text, so adding WhatsApp later is a delivery change, not a rewrite.
- **Manage counts:** an **Alerts** badge ("3 new") counts alerts to act on or look at. Waiting wastage and price news are left out of it: Day end already shows the first, and the second is not a problem.
- **Demo data note:** the demo generator moves a fake clock, but a void is stamped with the real time, so a freshly generated demo shows all its voids as one burst. That is the generator, not the rule.

### 9.11 Food courts: customers scan one QR and order from any outlet
Chosen from a mockup. Several shops (outlets) share one food court. A customer scans the court's QR (or opens /order), logs in, picks an outlet, picks dishes and gets a token (9.13 changed this from "no login"). The outlet sees the order on its own Tables screen. **Payment is at the counter** in this version.
- **How an order travels.** The customer's order is an ordinary takeaway `Order`, written as the same events a till writes (`open`, `kot`) by a stand-in "Online ordering" device and user. So the outlet gets, with no new code on its side: the kitchen screen, the "your order is ready" message (when the customer agreed), billing with GST and an invoice number, the receipt message, and the reports.
  - *Trade-off:* the stand-in user and device (code `ON`) are hidden from the Staff and Tablets lists. The token is written at the front of the customer's name ("JT-17 Ravi") because the order rules are pinned to the app by shared test cases; adding a field there would change both.
  - The customer's page says **Received → Ready → Collected**. There is no "Preparing" step: the order machinery has no such event, and adding one would change those pinned rules.
- **Who sets it up: the super admin** (README, 9.12). Owners no longer make, join or leave a food court. Each outlet's owner sees the court, its QR and one switch, **Taking online orders** (Manage → Food court), which is off until the owner turns it on.
- **What a customer can reach (`/api/v1/public/...`).** The outlet list (names and open/closed), one outlet's menu (dish names, categories, prices, sold out) and reading one order back are open to anyone. Placing an order and the list of courts need a customer account (9.13). Nothing else.
  - The shop a request touches comes from the food court's own outlet list, never from anything the customer sends. A dish id from another outlet, or an outlet from another court, is refused.
  - The order link is signed (HMAC over the shop and order ids): changing one character, or pairing one shop's id with another's order, finds nothing.
  - Limits: 5 orders per hour per phone number, 40 open online orders per outlet, 20 of one dish, 15 dishes, 40 items in all. A double tap is one order (the page sends one id per order).
  - `FoodCourt` and `FoodCourtOutlet` belong to no single shop, so they are not tenant-scoped: every function that reads them is given the shop id from the token (or the super admin's ids) and checks the rest by hand. All the food court tables have row-level security on.
- **Sold out.** A switch beside each dish under Menu prices & GST. It switches itself back on in the daily cron, so a forgotten switch never hides a dish for good.
- **Migration** `027da6efe82c`: three new tables and one column with a default, nothing removed. Apply it to Supabase by hand before this code is merged (README, "Parallel migrations").
- **Not built, on purpose:**
  - **Online payment.** Today every shop shares one Razorpay account (its keys are server settings, not per shop), so online payment would put every outlet's money in one account. Per-outlet payment needs each outlet's keys stored encrypted and its own webhook. That is a project of its own.
  - **One order across outlets.** The cart is shared (9.13) but each outlet still gets its own order: that keeps each invoice, stock deduction and refund inside one shop.
  - **A phone check (OTP).** The phone number is typed, not proved (see 9.13).
  - **A sound or push when an order arrives.** The Tables screen shows "Online orders (n)" first and refreshes with the other live orders.

### 9.12 The super admin: food courts and their outlets
Chosen from a mockup, replacing the first design where one outlet's owner "hosted" the court and invited the others by a code. A food court belongs to nobody's shop, so someone above the shops has to make it: the **super admin**.
- **Who they are.** A row in `platform_admins`, deliberately not a `User` (a user always has a shop and a role inside it, and every shop-level check is built on that). Signing in is `POST /platform/login`; the token has `type: platform`, no shop and no role.
  - **The two worlds never mix, in both directions, and both are tested.** Every shop route requires a shop and `type: access`, so a platform token is refused there. Every `/platform` route requires a platform token, so a shop owner's or cashier's token is refused there. A switched-off admin is out at once, not when the token expires.
  - Wrong passwords lock the account for a while, the same rule as shop users. A wrong number and a wrong password get the same answer.
  - The token lasts 8 hours and is kept in the browser tab only. The admin page is used rarely, so there is no refresh token (those belong to a shop).
  - **There is no screen that makes a super admin**: `python -m scripts.new_platform_admin` (`NEW_ADMIN_PHONE`, `NEW_ADMIN_PASSWORD`), run by someone with the database. `./local.sh` makes one for local use (9000000099).
- **The admin page is `/admin`** (a page like `/order/<court>`; signing in decides who may do anything). It lists courts with their QR, link and outlets, and has:
  - **New food court.**
  - **Add outlet**, two ways: a **new** outlet (a shop, its owner's login with an optional temporary password the owner must replace at first login, and optionally the sample menu), or an **existing** shop attached by its owner's mobile number. A cashier's number does not attach a shop, and a shop in one court cannot be in two.
  - **Open or close** an outlet, and **remove** one. Removing only takes the shop out of the court: its shop, menu, login and orders are untouched. The admin can close an outlet, and its owner can open it again (the owner's switch is the owner's).
  - **Print the QR** for one court.
- **API:** `/api/v1/platform/...` (`api/v1/platform.py`, `services/platform.py`). Outlet ids are checked against the court in the URL: an outlet of another court is simply not found. These routes carry ids but are not shop routes, so the shop-versus-shop gate excludes `/platform` (as it does `/public`) and `tests/test_platform.py` covers who can reach them.
- **Migration** `b4bb997f2f3c`, on top of `027da6efe82c`: the `platform_admins` table (row-level security on), `food_courts.host_shop_id` and `join_code` made optional, and `food_courts.created_by`. Nothing removed: `join_code` is retired but kept so dropping it can be a later, separate step. Apply both to Supabase by hand before merging.
- **Moved into the app:** making a shop (`services/shops.py`) and the sample menu (`services/sample.py`), because the deployed app does not include `scripts/`. `scripts/new_shop.py` and `scripts/seed.py` now call them.
- **Not built:** several admins with different powers, a way to sign an admin out everywhere, and changing an admin's password in a screen (`./reset-password.sh` resets them locally).

### 9.13 Customer accounts, choosing a food court, and one cart across outlets
Chosen from mockups. A customer has an account (mobile number + password), picks a food court from a list (or a QR skips that), puts dishes from any of its outlets in one cart and places it: **one order and one token per outlet**.
- **The account.** `customer_accounts`: a name, a mobile number and a password hash, belonging to no shop. It is deliberately neither a `User` (staff, tied to a shop) nor the shop-level khata `Customer`. Sign-up and log-in are `POST /customer/signup` and `/customer/login`; the front door is `/order` (a court's QR is `/order/<court>` and goes straight to that court after log-in).
  - **Own token type** (`type: customer`, 30 days, no refresh). The three worlds never mix, in every direction, and it is tested: a customer token opens no staff, admin or court-management route, and a staff or admin token opens no customer route. A password change or reset bumps the account's `token_version`, so it logs the account out on every device at once; a switched-off account is out at once.
  - **Same rules as staff logins:** five wrong passwords lock it for 15 minutes; a wrong number and a wrong password get the same answer. Password rules are the staff ones (8+ characters, not a common one, not the phone number).
  - **Forgotten password: the super admin resets it** (`/admin`, "Forgotten customer password"). They get a temporary password, shown once, to read to the customer, who must replace it at the next log-in (the app will not go further until they do). A reset also clears a lockout. *Trade-off:* one accountable person, not each outlet, so an outlet cannot lock out a rival's customers. The cost is that someone takes the calls.
- **The number is not verified.** There is no SMS, so nothing proves a customer owns the number they typed. Someone could sign up with another person's number and the outlet would ring that person about the order. Acceptable for pickup with payment at the counter. SMS login later is a contained change (the log-in becomes a code, the account table stays). Sign-up also tells you a number already has an account ("log in instead"): the usual price of a friendly message.
- **Ordering needs the account** (`POST /public/courts/.../orders` now takes a customer token). The name and phone on the order are the account's, not typed, and the order is linked to the account (`online_orders.customer_id`). Reusing someone else's `request_id` finds nothing.
- **My orders** (`GET /customer/orders`) lists their orders across every outlet, newest first, each with its token and live status. The query is by customer, in a system session, because the orders live in different shops.
- **Choosing a court.** Courts have a **location** the admin types ("Marina Beach, Chennai"); the signed-in customer picks from `GET /public/courts` with a search by name or place. Courts with no outlet are not listed. *Not built:* "near me" by GPS, which needs coordinates per court and a location permission.
- **One cart.** Outlets are tabs inside the court; the cart keeps every outlet's dishes (and is kept on the phone per court). The cart groups by outlet with a subtotal each; each outlet's total is worked out the way that outlet's bill will be (the shared GST code), then added. **Place** sends one order per outlet, one after another, each with its own id. If one outlet is busy or just sold out, the others still go through, and the failed one stays in the cart to retry.
  - *Trade-off:* the orders are placed one by one, not as one transaction, because each outlet is a separate shop with its own till. The failure case above is the price; the alternative (all or nothing) would let one closed outlet block the rest.
- **Not built:** several phone numbers per account, a way for a customer to change their own number or delete their account, rate limits on sign-up (a real limit needs shared state serverless does not give for free; add before opening to the public), and any payment beyond "pay at the counter".
- **Migration** `c7d1a9e5f302`, on top of `b4bb997f2f3c`: the `customer_accounts` table (row-level security on), `online_orders.customer_id` (nullable) and `food_courts.location` (default empty). Nothing removed; apply to Supabase by hand before merging, after the two before it.

### 9.14 Paying online for a food court order
Chosen with the owner: **all money goes to the app's one Razorpay account** (the operator settles with each outlet afterwards), and the customer **chooses per order**: pay online (UPI or card) or pay at the counter.
- **The flow.** The cart is checked at every outlet and priced by the server (`onlinepay.start`); one Razorpay order is opened for the total (`POST /customer/checkout`, nothing is sent to a kitchen). The customer pays on Razorpay's page, which lives on the **API** and opens in a new tab (the app's security policy allows no third-party script because the app keeps a login token in the browser; the till's payment page works the same way). Once Razorpay confirms (Checkout's signature, then a look at the payment itself, or Razorpay's webhook, whichever comes first), each outlet's order is placed with what was paid for it (`onlinepay.fulfil`) and the customer's page, which was waiting on `GET /customer/checkout/<id>`, shows the tokens marked **Paid**.
  - Reuses the till's Razorpay code (`services/payments.py`: the signature check, capture of an authorized payment, the webhook route and its secret). `OnlinePayment` deliberately has the same column names as the till's `Payment` so that code works on both. No new keys: the same `RAZORPAY_*` settings. With no keys, "pay online" is not offered (the public court says `online_payment: false`).
  - **Idempotent at every step.** The page makes the payment id (a second tap is the same payment, not a second charge; a changed cart gets a new id); each outlet's order keeps its own request id; a retried verify, a second webhook and a customer reopening the page change nothing. Each outlet's part is decided and saved on its own, under a row lock, so a crash halfway is finished by the next request.
  - **A paid part that cannot be placed is refunded** (the dish sold out, the outlet closed or got busy, a price moved while the customer paid: an order is never served for a different amount than was paid). Only that outlet's share is refunded, through Razorpay, and the customer's page says so in words. If the refund call itself fails, it is left in the admin's "Refunds to make" list; it is never lost and never sent twice.
  - A paid order is **not subject to the per-phone hourly limit** (real money is a better brake than a counter); the other limits still apply.
- **At the outlet.** The Online orders card shows **Paid online ₹X** (from `GET /orders/online-paid`, a separate small call so the order rules, pinned to shared test cases, do not grow a field). The outlet records the sale as **UPI**.
  - *Trade-off:* there is no separate "paid through the food court" payment mode, because that would touch every report. So the outlet's own UPI total includes money that actually went to the operator. If this confuses day-end counts, the clean fix is a new mode (additive, but it touches the reports).
  - An order the outlet **cancels after payment** is not that outlet's money: it leaves the outlet's total and appears under "Refunds to make", where the admin refunds it (manual on purpose, so an outlet cannot trigger refunds by itself).
- **Who is owed what.** `GET /platform/online-money` and the **Online money** section of `/admin`: per outlet, paid by customers, settled, owed. The admin records a payment made to an outlet (`OnlineSettlement`, capped at what is owed). The outlet's owner sees the same three figures for their own outlet under Manage → Food court (read-only).
- **Local test mode: `FAKE_PAYMENTS`.** Without Razorpay keys "pay online" is not offered, so `./local.sh` (via docker-compose) turns on pretend payments: the cart offers it, the payment page is a local "Pay (test)" page (and a "make it fail" button), and nothing is charged. It uses the same code path as real payment (the same order, confirm, place and refund steps) with a stand-in for Razorpay's three calls, so what you see locally is what the real flow does. It is refused unless the database is on this computer and never with `ENV=prod`, the same guard as `DEV_LOGIN` (both tested), and it never turns on the till's own Razorpay payment. The browser test uses it, so CI runs the whole flow.
- **Not built:** automatic payouts to outlets (Razorpay Route, which needs each outlet's own KYC; this version is a ledger plus a manual transfer), a separate payment mode for outlets (above), partial refunds of a single dish, and a browser test of Razorpay's real checkout (it cannot run in CI; the browser test uses the pretend mode above, and the money logic is tested against a fake Razorpay in `tests/test_online_payments.py`).
- **Before going live:** test mode first (`rzp_test_` keys), then a few real small orders settled with one outlet end to end. Live keys need Razorpay's approval for the account. The webhook must be set up (the same one the till uses) or a customer who closes the page without letting the confirmation reach us depends on reopening it.
- **Migration** `d8e2b6f4a113`, on top of `c7d1a9e5f302`: `online_payments` and `online_settlements` (row-level security on) and three columns on `online_orders` (`payment_id`, `paid_paise`, `refunded_paise`). Nothing removed; apply to Supabase by hand before merging, after the three before it.

### 9.15 Food court extras: options, photos, ready notices, till alert, order again, wait time, ratings
Chosen from mockups; "offers" were deliberately left out (below).
- **Dish options.** A customer can pick the options the till already offers (Large, less sugar). `online._load_mods` builds each option from the outlet's own definitions and saves it on the order **exactly as the till saves it** (name, price change, size factor, stock change), so billing, stock deduction and the kitchen need no new code. Nothing about an option's price or stock effect comes from the phone, and an option the dish does not offer, one switched off, or two sizes at once, is refused. The same dish with different options is a separate line, and the GST total on the phone and on the server use the same shared rule with each option's price change (a test pins the same number on both sides).
  - Options that change the size (`scale_factor` other than 1) are shown as "Size" (pick one); the rest are tick boxes. A paid cart whose option goes off while the customer pays is refunded for that outlet like any other part that cannot be placed.
- **Description, picture, veg mark** per dish (Manage → Shop & GST → a dish). **Eight pictures ship with the app** (`frontend/public/dishes/*.svg`: tea, coffee, juice, snack, meal, biryani, roll, dessert): the editor shows them as a picker, one tap to choose, "Remove picture" to take it off, or the owner pastes a link to their own photo (`https://` only). The backend accepts exactly an `https://` link, one of those `/dishes/<name>.svg` paths, or nothing (`schemas_catalogue._secure_photo`); the app's content policy allows `img-src https:` for linked photos. The sample dishes (Masala tea, Orange juice) are given a picture, line and veg mark by `seed_catalogue`, and `python -m scripts.add_dish_pictures` (run by `./local.sh`) fills the same in shops made before pictures existed, **only where a dish has neither a picture nor a description**, so nothing an owner set is overwritten. *Trade-off:* the host of a photo sees a customer's address (no referrer is sent). *Not built:* uploading a photo from the phone, which needs a storage service and keys to be chosen first.
- **Ready notice on the customer's phone (Web Push).** Written out in `services/webpush.py` (RFC 8291 encryption, RFC 8292 VAPID) with `cryptography` and `httpx`, not the `pywebpush` package, because that needs `http-ece`, which does not build everywhere (it did not here). `tests/test_webpush.py` decrypts a message the way a phone does. When every dish on a customer's online order is ready, `extras.notify_ready` sends one notification (claimed first, so it is never sent twice), to that customer's phones only; a phone that has forgotten the subscription is dropped; a failing push service never breaks the kitchen's screen.
  - **Keys.** `python -m scripts.make_vapid_keys` makes a pair: put `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` in the server's environment (Vercel env vars). The private one is a secret: you type it yourself, it never goes in the repo or in chat. Keep the same pair for good (changing it makes every phone's subscription stop working). With either unset, push is off and the page only chimes when it is open. `./local.sh` makes a pair for your computer (`.local-vapid.env`, git-ignored).
  - **iPhone** needs the app added to the Home Screen first (an Apple rule); Android Chrome works in the browser. Nothing here costs per message.
  - The page also chimes, buzzes and changes its tab title the moment the order turns ready while it is open (no keys needed).
- **A ring on the till** (`OnlineOrderAlert`). A pink banner and a chime when a customer's order arrives, on whatever screen the till shows, repeating every 20 seconds until someone taps it. One "Sound" switch per tablet, remembered on it (browsers only allow sound after a tap). A tablet takes its first sync as the baseline, so it never rings for the queue already waiting.
- **Favourites and order again.** A heart on a dish (`customer_favourites`); hearted dishes are listed on the front page and open that outlet. "Order again" on a past order puts the same dishes and options back as that outlet's cart and opens it; the cart checks the outlet's menu as it loads and leaves out (and says so) anything that is gone. Prices and availability are always looked up fresh.
- **Usual wait.** An outlet owner sets "usually ready in about N minutes" (Manage → Food court); customers see it on the outlet's menu and on the token while it is received. It is the outlet's promise, not a computed guess.
- **Ratings.** After an order is collected the customer rates it 1 to 5, once, with an optional line (`order_feedback`, belongs to the outlet's shop). The owner sees their average and recent comments (first names only); the admin sees every outlet's average on its list.
- **Offers: not built, on purpose.** A discount changes the GST (tax is worked out on the lower price), so the customer's total, the outlet's bill, refunds and the outlet's payout all have to agree to the paisa, which is the riskiest part of the money code; and someone must fund it (the operator, the outlet, or both), which is a business rule to decide first. Run these on real orders and design offers around what sells.
- **Migration** `e9f3c7a5b224`, on top of `d8e2b6f4a113`: new columns on `menu_items`, `food_court_outlets` and `online_orders` (all with defaults or nullable) and three new tables with row-level security (`order_feedback`, `customer_favourites`, `push_subscriptions`). Nothing removed.

### 9.16 Tamil, AI helpers, and three watches
Chosen after research into what small shops and food courts complain about (aggregator commissions, staff taking UPI to a personal QR, owners who cannot type in English, software that edits bills). The research was vendor blogs and news, not owners' own words, so treat the pains as likely, not proven.

**Tamil and English.** `lib/i18n.ts`: the English text *is* the key, `t("Add to cart · {price}", {price})`, so a missing translation shows English instead of a blank, and `{values}` move freely because Tamil puts the verb last. Tamil lives in one file, `lib/ta.ts` (a test checks every entry has Tamil and the same `{values}` as its English). The choice is kept on the device; every screen that calls `useLang()` redraws at once. A switch sits on the customer pages, in the account sheet (Today → Account, and the name in the top bar on a tablet), with the voice settings.
- **Covered in Tamil:** the whole customer app (sign-up, courts, menu, options, cart, paying, tokens, orders, ratings, errors), the till (log-in, New bill, Today, kitchen, account), the Manage menu, and every new screen below. **Added in 9.17:** Manage → Khata, Stock, Shop & GST, Staff, Tablets, Messages, Floor, cash drawer and discount settings, email settings, wastage to check, and printer settings (whole labels and sentences; a few sentences built from pieces stay English). **Still English:** the dine-in order screen, day-end counting, recipes, purchases, reports, sales, the super admin, receipts (a bill is a document), and messages that come from the server (for example "Not enough stock"). A customer sees a dish's Tamil name and description when its outlet wrote them (`menu_items.name_ta`, `description_ta`; Manage → Shop & GST → a dish, with "Write in Tamil for me"). *Why one dictionary and not a library:* no new dependency, no key catalogue to keep in step, and it degrades to English. *Trade-off:* the English text cannot be reworded without also editing its Tamil key.
- Numbers, ₹ and phone numbers stay as digits in both languages on purpose.

**The AI helpers** (`services/ai.py`, routes `/ai/*`, owner only). Every helper asks the model for **structured JSON** and then checks it in code; the model proposes and explains, it never writes stock, money or bills.
- `ANTHROPIC_API_KEY` switches them on (`AI_MODEL`, default `claude-opus-5-5`; `claude-haiku-5-5` costs about 40 times less and is likely enough for these small jobs, so try it). Without a key every screen says "not switched on" and the rest of the app is unchanged. The key is a secret you type into Vercel yourself; locally, put `ANTHROPIC_API_KEY=...` in `.local-ai.env` (git-ignored). **`FAKE_AI=true`** (local only, refused with a remote database or `ENV=prod`, like `FAKE_PAYMENTS`) swaps in simple rules so the screens can be tried and tested for free; a real key replaces it.
- **A daily ceiling per shop** (`AI_DAILY_LIMIT`, default 60 calls; table `ai_usage`). It is counted *before* the model is asked, so a failing model cannot be used to run past it, and one "Ask your shop" question is one allowance even though it asks twice.
- **Buy by voice or photo** (Manage → Stock → Buy). The owner speaks (the browser's own speech recognition, Tamil or English; no key), types, or photographs the supplier's bill (shrunk to 1600 pixels in the browser first). The server turns it into a **draft**: the stock item must be one of this shop's buyable items (never a prep item, never another shop's), litres/kg/dozens become base units by arithmetic, money becomes paise from a decimal string (no floats), a unit that does not fit the item ("kg" for milk) is flagged, and the lines are added up against the bill's printed total. Nothing is saved until the owner checks it and taps Save; saving is the ordinary `/stock-in`, one per line, so the ledger rules are untouched (and the "much more than usual" check still asks).
- **Why is the stock short?** (Day end → "Why? Explain this day"). `ai_insight.day_facts` lists the facts from the records (each item outside tolerance, voids, discounts, cancelled items, wastage), each with an id. The model writes a short summary and attaches a reason to the facts that plausibly explain a gap; a reason that does not point at a real fact id is dropped. A quiet day makes no call.
- **Ask your shop** (Manage → Money → Ask). The model only *chooses* one of seven fixed reports (sales, best sellers, wastage, low stock, voids, UPI, GST turnover) and a period; fixed code runs it; the model then phrases those lines in Tamil or English. It never writes a query and cannot change anything; "delete every bill" lands on "unknown" and is not run.
- **Dish names in Tamil.** The owner taps once, the boxes fill, the owner reads and saves.
- **What leaves the app.** Each call sends the shop's own words or numbers to the AI company's servers: the owner's typed or spoken note and the bill photo (Buy), the question and the fixed report lines (Ask: sales, item names, staff names on voids, amounts), the day's facts (Why: item names, staff names, amounts) and a dish's name and description (Tamil names). It never sends a customer's phone number, a password, a token or another shop's data. Anthropic's terms say whether API inputs are used for training; read them for your plan before you put a real shop on it.
- *What I could not test:* the real model (no key in the build environment). The request the app sends is checked over a stand-in connection (`tests/test_ai_purchase.py`: model, JSON schema, low effort, no `thinking`/`temperature` parameters, which the newest models reject; refusals, a busy service and a garbled answer give plain messages), but real Tamil speech, real Tamil translations and real bill photos need your phone and your key. The first week of real use is the test.

**Speaking aloud** (`lib/announce.ts`, `lib/voice.ts`; account sheet → "Speak tokens and payments aloud", per device, off by default). "Token JT 17 is ready" when the kitchen taps ready on an online order, "₹60 received" when a Razorpay payment lands, "New online order" when one arrives. It uses the device's own voice (no key, no cost); with no Tamil voice installed it speaks English instead of badly or not at all. Browsers need one tap before they will make sound, so the switch and "Test voice" are that tap.

**Three watches** (Manage → Money → Watch; owner only), all worked out from the records:
- **UPI match** (`services/upimatch.py`). Every UPI bill (or UPI part of a split) against the money Razorpay confirmed for that bill: bills with no confirmed payment, a different amount, and money confirmed for a bill that was then voided, with a count per cashier. It answers the staff-takes-UPI-to-a-personal-QR problem. It only means something when the shop takes UPI through Razorpay (it says so otherwise). Two or more unconfirmed UPI bills in 7 days become an alert.
- **Changes and a bill's history** (`services/trail.py`). A day's voids, discounts, cancelled items and late-synced bills, and for one bill a timeline: who rang it, what was taken off and why, the running order's events, the payment, the void. **A bill can no longer be edited or deleted, by anyone:** the migration adds a database trigger (`bills_guard`) that refuses any update except completed → void with every other column unchanged, refuses deletes, and makes `bill_voids` append-only, the same way the stock ledger and order events already are. The app never did either; now ad-hoc SQL cannot. *This is protection against edits, not a signature:* someone with full database access could still drop the trigger, so it deters casual tampering and makes it visible; it does not prove a bill was never altered.
- **GST limit** (`services/gstwatch.py`). Turnover before GST for the financial year (1 April to 31 March, voids left out) against a registration limit **the owner types after asking an accountant** (`shops.gst_threshold_paise`); the app does not guess it because it depends on goods or services and the state. It shows how full the limit is and, at the pace of the last 60 days, the date it would be passed; 80% or more is a "look" alert, past it an "act" alert. A registered shop sees only its turnover.

**Not built from the research:** WhatsApp/phone ordering bots (owners rank front-of-house AI last, and the market is crowded). **A question to settle with a GST accountant before the first live food-court payment:** CGST section 9(5) makes the *operator* of an e-commerce platform liable for GST on restaurant services supplied through it. Whether a food court app that collects customers' money counts as one, and so whether you owe that GST yourself, is not something I could establish.

**Migration** `f1a5c9d3e446`, on top of `e9f3c7a5b224`: `ai_usage` (with row-level security), `menu_items.name_ta/description_ta`, `shops.gst_threshold_paise`, and the two database guards above. Nothing is removed; the guards are the one thing to know before applying it by hand: a script that edits or deletes bills would now fail.

### 9.17 Round two: phone codes, outlet statements, owner helpers, pickup times, display board, photos
Decisions and trade-offs, in the order they were built.

**Phone check at sign-up, and "forgot password" by code** (`services/phone_codes.py`, `ratelimit.py`). A 6-digit code is sent to the customer's number and typed back. Codes are stored only as an HMAC (the database never holds a usable code), live 10 minutes, allow 5 wrong tries, 30 seconds between sends and 5 sends an hour per number. **It switches on only when something can send a code** (`phone_codes.set_sender`, or locally `FAKE_SMS=true`, which shows the code on screen and is refused with a remote database or `ENV=prod`, like the other pretend modes). *No real SMS provider is included:* that needs a paid account and a DLT-registered sender in India, which only you can set up; the seam is one function. Until then sign-up works exactly as before and says nothing about codes, so an unverified number is still just a login name. Forgot-password answers the same whether or not the number has an account, so it cannot be used to find who is a customer. The super admin's temporary-password reset stays as the fallback.
- **Sign-ups are limited per address** (8 an hour; the address is the first `X-Forwarded-For` hop, which a host's proxy sets). *Trade-off:* a whole food court on one wifi shares an address, hence 8 and not 2; a determined script can still rotate addresses, which is why the code check matters more.

**Outlet statements, the operator's fee, automatic refunds** (`services/onlinepay.py`). Each outlet has a fee in basis points set by the super admin (`food_court_outlets.fee_bp`, 0 to 30%). The fee is worked out **per paid order, rounded half up**, never on the total, so the statement adds up to the paisa whatever the range. Owed = paid − fee − already paid out. The owner sees a statement for any range of up to 92 days with a CSV (Manage → Food court); the super admin sees any outlet's. *The fee applies to all of an outlet's online orders from now on, including old ones:* changing it moves the number owed, so settle before changing it.
- **Cancelling a paid online order refunds it at once** (a hook after the outlet's sync, best effort and idempotent). A refund that fails stays on the admin's "refunds due" list, so nothing is lost; it can never be refunded twice.
- **"Paid via food court" in the UPI match:** a UPI bill whose order was paid in the app is left out of the "no confirmed payment" list and shown as a separate amount, because that money went to the food court's account, not the shop's. Derived from the order, so there is no new payment type to keep in step.

**Owner helpers** (Manage → Money → Helpers).
- **Commission calculator:** you type the month's app sales, the commission and what a direct order costs; it shows what you paid, what direct would cost and the difference. It does not know what any app charges you and says so. The numbers are kept on that device only.
- **Tomorrow's prep:** for each bought ingredient, the average of what the shop used on the same weekday over the last four weeks (sales and batches made, less voids). A plain average, owner only (it is about stock). *Not a forecast:* a holiday or rain breaks it, and it says "a guide, not a promise".
- **Hide a dish when its ingredient runs out** (`services/autosoldout.py`, off by default): only for bought ingredients that were once counted, and only when what is left is less than one dish needs. Made-in-shop items (the decoction) are never judged by the shelf. The check runs when the menu is shown and again when an order is placed, so an order for a dish that just ran out is refused with "Sold out".
- **Daily summary message** (`services/summary.py`): a few lines (sales, bills, cash/UPI, top three, what needs you) to the owner's mobile through the same provider as customer messages (Inkbox iMessage). *It says WhatsApp in the mock-up, but WhatsApp's business API needs an approved template and account that only you can open, so this goes where the shop's messages already go.* With no provider it is only shown on screen ("Send me one now" shows the exact text). It is sent by the existing daily job.

**Pickup times** (`online.slots`, `check_pickup`). A customer may choose a time instead of "as soon as possible": 15-minute slots from ten minutes ahead (or the outlet's usual wait if longer) for three hours, never past midnight. Each outlet sets how many orders a slot takes and can switch times off. A full slot refuses an *unpaid* order; **an order already paid for is never turned away because its slot filled while the customer paid** (the time is only checked for shape). The kitchen screen holds an order for later until 15 minutes before its time, then shows "For 1:15 pm". *The order rules shared with the tablet were not changed:* the time and table ride in the same small call as "paid online" (`/orders/online-paid`).

**Table QR** (Manage → Food court). One QR per table, `/order/<court>?outlet=<id>&table=<name>`: it opens that outlet's menu and the order says "Table 4" in the outlet's order list. It is a convenience, not a security check: anyone can type any table name, so the outlet confirms by looking.

**Display board** (`/board/<court>`, `GET /public/courts/<slug>/board`). A page for a TV: ready tokens big, tokens being made smaller, a spoken call in English (and Tamil where the device has a voice) when a token turns ready. No login; **only tokens and outlet names leave the server, never a name or a number.** Browsers will not make sound until someone taps, so sound starts with one tap, and the first look at the board calls nothing (a screen switched on at noon does not shout every token waiting).

**Dish photos from the phone** (`dish_photos`, `POST /menu-photos`, `GET /public/dish-photos/<id>`). The phone shrinks the picture to 800 px and 300 KB; the server checks again (400 KB at most, and the type comes from the file's first bytes, never from what the sender says: JPEG, PNG or WebP only), keeps it in Postgres and the dish keeps a short link. It is served with `nosniff` and a locked-down content policy. *Trade-off:* the database is not made for pictures; at 300 KB and 300 photos a shop that is about 90 MB, fine for a handful of shops and a reason to move to object storage later. A photo you replace is not deleted (no clean-up job yet). The web app's content policy now also allows images from the API address.

**Left out on purpose:** offers and coupons (they change what money is owed and need rules to be agreed first), ONDC, Swiggy/Zomato intake, one login for several outlets, and a real SMS or WhatsApp sender.

**Migration** `a2b6d1f4c557`, on top of `f1a5c9d3e446`: tables `phone_codes`, `rate_hits`, `dish_photos` (all with row-level security), and the columns `food_court_outlets.fee_bp/pickup_enabled/pickup_capacity`, `online_orders.pickup_at/table_name`, `shops.auto_sold_out/summary_phone/summary_on`, `customer_accounts.phone_verified_at`. Additive only.

### 9.18 Round three: your usual, what you wasted, shift notes, token page without signal, busy pause
**Your usual** (`customer_accounts.usual`, `GET /customer/usual?outlet_id=`). On an outlet's menu, a customer who has ordered there at least twice sees the dishes in two or more of their last eight orders there, in the quantity they most often take (the smaller on a tie), up to four. One tap fills the cart. Only dishes still on the menu, not sold out, with their options still offered are shown, and prices are looked up fresh like "order again". It disappears once the cart has something in it. *No machine learning:* a count of their own past orders.

**What you wasted** (Manage → Money → Helpers; `services/wasted.py`, `GET /reports/wasted`). The last 28 days of wastage entries: total, the top five items, the weekday with the most and its main reason. *Only entries that count as a known loss are added* (approved): a cashier's large entry still waiting for you, and one you rejected (which is added back to stock), are left out. **Not built:** "sold out most", because the app does not record when a dish is switched sold out (the flag resets each night), so there is nothing honest to count; recording it would be the next step.

**Shift handover note.** The end-shift sheet already had a note box; it is now "Note for the next shift", with the microphone. The note travels with the shift's close, and the next person sees it on the Start-shift sheet ("From Ravi, for this shift"), also on a tablet that was reset (the server returns it with the last count). *There is no "got it" tick:* the note shows once, when the next shift starts.

**Token page without signal.** The customer's token card keeps the last state this phone saw (also across a reload, in the phone's own storage), and shows "No signal. Last updated 2 min ago. We keep trying." while polls fail. A 404 still says the order was not found; other failures are treated as lost signal. *It cannot know the order moved on while offline;* it says how old the information is instead of guessing.

**Pause when busy** (`online.check_not_busy`; Manage → Food court). Off by default. When on, once an outlet has N open online orders (default 12, 2 to 40) new unpaid orders are refused and a ten-minute pause starts by itself; customers see "Very busy: back at 1:25 pm" and cannot add dishes; the owner sees the pause with "Open now". Switching the feature off lifts a running pause; raising the limit does not (use "Open now"). **An order already paid for is never refused**, and the check also runs when a payment is started so nobody pays for an order that would be turned away. The older hard limit of 40 open orders stays as the last guard. *Trade-off:* it counts open orders, not minutes of work, so a single large order counts as one.

**Migration** `c3d7e2a9b668`, on top of `a2b6d1f4c557`: `food_court_outlets.busy_pause_on/busy_limit/paused_until`. Additive only.

### 9.19 Round four: offers, linked outlets, sold-out history, "got it", more Tamil
**Offers** (`services/coupons.py`; Manage → Setup → Offers; the customer types the code in the cart). An outlet makes a code: a percentage (with an optional cap) or whole rupees off, an optional smallest order, last day and total number of uses. **The server decides everything:** the page sends a code; the amount off, whether it still works and what the customer pays are worked out there, by the same rule the till uses when it bills the order, so the bill equals what the customer owes to the paisa.
- The discount is a **whole number of rupees** (a percentage is rounded half up to the rupee, then capped) and is the bill-level discount the till gives the order; the amount paid is `compute_bill(lines, discount).total` on both sides. **At least ₹1 is always payable** (a 100% code would mean a payment of nothing, which the payment service refuses).
- **The outlet pays for its own offer.** The food court's fee, the statements and refunds all use what the customer actually paid. A customer uses a code **once**; a cancelled order gives its use back; a total limit counts non-cancelled uses (the coupon row is locked while an order is placed, so two customers cannot both take the last use).
- **An order already paid for keeps its discount** even if the code ran out or was switched off while the customer paid; an unpaid (pay at the counter) order is checked in full again when it is placed.
- **At the till** an order with an offer shows "Offer CODE", the settle sheet says what is off, and the order is billed with exactly that discount (reason "Coupon CODE"). Because it is the outlet's own offer, such a bill is **not** flagged "over the cashier's limit"; the same discount typed by a cashier on an ordinary bill still is. **Split bill is hidden for an order with an offer** (the discount would have to be shared between parts; not built).
- Checking a code is limited to 30 tries an hour per customer so it cannot be used to guess codes; "invalid" says the same whether a code never existed or belongs to another outlet. What a code takes off is not editable after it is made (orders already used it); switch it off and make a new one.

**Several outlets, one overview** (`services/links.py`; Manage → Money → Outlets). **Not what you asked for, on purpose:** you asked for switching between outlets without logging out. A tablet's saved bills and its device belong to one shop, so swapping the login under it would mix two shops' data, and a token that works in another shop is the most dangerous thing this app could issue. Instead an owner **links** their owner logins (typing the other owner's number and password, checked with every login rule, never stored) and sees every linked outlet side by side: sales today, bills, what needs them, open online orders, and a total. The server reads each outlet through that outlet's own tenant session, so isolation is exactly what it was; **no token is ever issued from a link and nothing can be changed inside another shop** (to do that, log in there). Only owner logins can be linked, a cashier's cannot, a switched-off owner disappears from the list, and either side can unlink. *Trade-off:* someone holding an owner's unlocked session can see the other outlets' figures; the figures are the link's whole purpose.

**Sold out most, and "Got it".** Switching a dish to "sold out" is now recorded (`sold_out_events`; dishes hidden by the stock check are not, nobody switched them), and the Wasted card lists the dishes switched most in four weeks. A shift note now stays on Today until someone taps **Got it** (remembered on that tablet).

**Tamil, further:** Reports, Sales, Purchases, Recipes (and its editor), ingredients, stock items, bill options, day-end report, table-service and adherence reports, handovers and the menu editor, plus everything above. **Still English:** the super admin page, receipts (a bill is a document), messages that come from the server, and sentences built from pieces (a Tamil sentence cannot be assembled from English fragments, so those few lines stay whole in English).

**Migration** `d4e8f3b1c779`, on top of `c3d7e2a9b668`: `coupons`, `coupon_redemptions`, `sold_out_events`, `user_links` (all with row-level security) and `online_orders.coupon_code/discount_paise`. Additive only.

### 9.20 Real SMS and WhatsApp (Twilio)
`services/twilio_sender.py`: one small client for Twilio's Messages API (form POST, basic auth), behind a seam so tests check the exact request over a stand-in connection. It carries two things: **phone codes by SMS** (sign-up and forgot password), and the **owner's daily message by WhatsApp**. Customer receipts and "ready" messages are unchanged (iMessage through Inkbox): a WhatsApp message to a customer who never messaged you needs an approved template, which is not worth the setup for one-line notices.
- **Switching on** is four settings you type into the host yourself (never in the repo): `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_SMS_FROM` (a number in +… form, or a Messaging Service id starting `MG`) for codes, `TWILIO_WHATSAPP_FROM` for the owner's message. With the SMS settings present the sign-up page starts asking for a code by itself; with none, nothing changes. A failed send says "We could not send the code" (502) instead of pretending, and error text never contains a phone number.
- **What I could not test:** Twilio itself (no account here). The request is checked against Twilio's documented shape, but a real message needs things only the account owner can do in Twilio's console: **for SMS to India, a sender and message wording registered with the telecom regulator (DLT)**, otherwise Twilio or the carrier will refuse it; **for WhatsApp, a business sender**, and a message the owner has not recently written to the sender needs an approved template (the sandbox works for trying it after the owner sends its join word). The first real code is the test.
- **Not built, and why:** Swiggy, Zomato and ONDC order intake. They have no self-serve ordering API a small shop can use; each is a partner agreement with its own onboarding, and building against an imagined format would produce code that does not work. When one of them gives you API access, the place to plug in is an "outside order" that enters as an ordinary takeaway order, like a customer's. **Split bill on an order with an offer** is also still hidden: sharing one discount across parts would break the "bill equals what was paid" rule and the over-limit exemption.

### 9.21 Round five: order together, allergy tags, attendance, change log and more
**Order together** (`services/groups.py`; the 👥 button on a food court's page). A customer starts a group and shares the link; friends open it, log in and add dishes as usual; everyone sees who is choosing what; the host taps "Add everyone's dishes and pay", which brings the others' dishes into their own cart and closes the group, then pays with the normal checkout. **The shared list holds ids and quantities only:** prices and availability are looked up fresh at the host's checkout (the same pruning as "order again"), so a group cannot smuggle a price. Others see only the *name* a member joined with, never a phone number. A group lives six hours, holds ten people, takes five starts a day per customer and 30 join tries an hour; a missing, expired or someone-else's group all answer the same, so tokens cannot be probed. *No live socket:* the page looks every four seconds (a food court's wifi is not worth a promise of live). *Trade-off:* the host alone pays; splitting the payment between phones would need a payment per person and a refund rule, which is not built.

**Allergy tags and spice** (Manage → a dish; the customer menu). A fixed list (nuts, milk, gluten, egg, soy, fish, shellfish, sesame) and how hot (not spicy to hot), so a filter means the same on every outlet. Customers can hide dishes with a tag; the filter lives only for that visit (an allergy is a health fact, not something to store). **A tag is the outlet's word, not a guarantee**, and the page says "if an allergy is serious, ask at the counter".

**Staff attendance and pay** (`services/attendance.py`; Today → clock in/out; Manage → Setup → Attendance). Written on the server when someone taps, so it needs a connection (unlike a bill). One open entry per person. The owner sees hours and, where an hourly rate is set, pay: minutes × rate ÷ 60, integer paise, **rounded half up once per person for the whole range**, never per day. An entry still open is shown, never guessed; one over 18 hours is flagged as a forgotten clock-out. The owner can correct an entry; the correction is recorded.

**The change log** (`services/audit.py`; Manage → Setup → Changes). Who changed a menu price, GST rate or visibility, a recipe, an offer, a person (added, switched on or off, password reset, pay rate), the shop's GST and report settings, or corrected an attendance entry. It is written in the same transaction as the change (a failed change leaves no line) and **a database trigger refuses any update or delete**. It records money-and-trust changes only; bills, stock, orders and voids already keep their own histories.

**Prices paid** (Manage → Stock). What each ingredient cost per litre, kilo or piece over time, from stock-in entries that carried a price, and the latest against the average of the three entries before it. The "price went up 5%" alert already existed and is unchanged.

**Special days** (Manage → Money). The owner marks a festival; the screen shows what the same date brought last year against that weekday's usual. **Fixed-date national days are suggested; moveable festivals (Diwali, Pongal, Eid) are not guessed**, because a wrong date would mislead.

**Delete my account** (customer, My orders). Needs the password. **Removed:** the login, name and number on the account (kept only as an anonymous row, because orders and payments point at it), favourites, notification subscriptions, phone codes, rating comments, group membership, and every message still waiting to be sent. **Stays, and the page says so before the customer confirms:** the outlets' own order records. An order's events (the name and number as given) are append-only and hash-linked, and an outlet must keep its sales records for tax; this cannot be erased from here.

**What customers say** (Manage → Food court). The written comments of the last four weeks, summarised by the AI into two sentences and up to five themes. Needs at least five comments (fewer would be a guess dressed as a finding). Code checks the answer: a theme cannot be mentioned more times than there are comments, an unnamed theme is dropped, and the text is shown as plain text. The comments are sent to the AI company (words and star ratings only; no names or numbers).

**Save receipt as PDF** (customer, My orders). A plain summary of an order the browser's own print dialog can save as a PDF. It says it is the customer's own record, not a tax invoice: the outlet's bill is the invoice.

**The operator's overview** (the /admin page; `services/operator.py`). Every outlet side by side for a range: sales, fee kept, orders, rating, average wait (from the order to the last "ready" tap, on collected orders only), cancel rate; the three busiest hours; a weekday-by-hour heatmap; and a **settlement sheet** (CSV) of what each outlet is owed now, biggest first. Anything that cannot be known shows a dash, never a guess. Read through each outlet's own tenant session.

**Backups.** `python -m scripts.restore_check --source "$SOURCE" --scratch "$SCRATCH"`: dumps the live database (read only), restores it into a throwaway database on a *different* server (for example your own computer), compares the row count of every table, and drops the scratch database. A backup you have not restored is a hope, not a backup. Passwords stay in your shell. Supabase's own backups are separate: check your plan for how long they are kept and whether point-in-time restore is included.

**Not built, and why:** a weather-based prep forecast (one outlet's data is too thin for an honest forecast); tips (they carry GST and accounting questions an accountant must settle first); loyalty stamps (offers should run in a real shop before another money rule is added); a reminder pushed at the customer's usual time (it needs a scheduler that fires every minute; the free hosting plan runs jobs once a day).

**Migrations** `e5f9a4c2d880` (attendance, special_days, audit_events with its append-only trigger, `menu_items.allergens/spice_level`, `users.hourly_rate_paise`) and `f6a1b5d3e991` (group_carts, group_members, group_lines), all new tables with row-level security. Additive only.

## Phase 10: the v1 gaps (adherence trend, wastage approval, shift counts)

Three things the spec lists for v1 that make the day-end number trustworthy. All on **Manage → Day end** for the owner.

### 10.1 Recipe adherence, last 30 days
One row per counted ingredient: adherence over the closed days (100% = staff used exactly what the recipe says), a small line per day, and a verdict:
- **Steady gap: the recipe may need updating.** Every day off by about the same (spread of 6 points or less). The recipe is wrong, not the people.
- **Changes day to day: look at who was on shift.** Some days fine, some not.
- **On recipe** (within ±3 of 100), or **too few closed days** (under 3).

The headline is adherence weighted by value, so a gram of cardamom does not count as much as a litre of milk.

**Decisions and trade-offs**
- **Only approved days, read from what approval froze** (each line's expected quantity, count and cost) plus the day's sales and batch rows written before approval. An open count can still change, and a late bill that arrived after the close is not usage the count could have seen; the day report excludes it the same way. One query for the window, no new table.
- **Thresholds are simple on purpose** (`lib/dayend.trendVerdict`, unit-tested). They decide wording, not money. Change them once the pilot shop has a month of data.
- `GET /reports/adherence?days=30` (7 to 92), owner only.

### 10.2 A cashier's large wastage waits for the owner
A cashier's wastage worth more than the shop's limit (default ₹200, set under **Wastage to check**) is recorded as **waiting**. The owner accepts it (a known loss) or rejects it. The day cannot be closed while an entry waits.

**Decisions and trade-offs**
- **The stock leaves the ledger at once.** The milk did spoil; only the explanation waits. Holding the stock back would make the shelf and the books disagree until the owner looked.
- **Rejecting adds the stock back as new ledger rows** (`ref_type = wastage_rejected`), never an edit. The loss then shows as missing at day end, which is the point: an unaccepted excuse is unexplained loss.
- **Owner entries and small ones never wait.** The limit is in rupees at cost, not quantity, because a litre of milk and a kilo of cardamom are not the same decision.
- **After the day closes**, a waiting entry can be accepted but not rejected: rejecting would move stock on a day whose count is final.
- Cashiers see "Waiting for the owner" / "Not accepted" on their own entries, still with no rupees.

### 10.3 Milk and fruit counted at each shift change
**Stock → an item → Count it: Every shift** adds the item to a blind count at the start of **End shift**. It changes no stock; it splits the day's gap by when it opened, so the owner sees **Shift handovers**: each period, who was on duty, and what went missing in it.

```
expected at T = the day's opening + stock-in, batches and wastage entered by T
                - sales rung up by T
gap at T      = counted - expected at T
gap in period = gap at T - gap at the previous count of the item today
```

The day-end count closes the last period, so the periods add up to the day's variance to the paisa (`test_phase10.py` works one day by hand).

**Decisions and trade-offs**
- **Sales are timed by the bill, not by when the server heard of it.** A tablet that was offline at 10 am still sold the tea before the 3 pm count. Other movements (stock-in, batches, wastage) are entered online, so their server time is right.
- **Computed when asked, not stored.** A bill that syncs late moves into the right period on the next read; nothing frozen goes stale.
- **Two counters share one shelf.** A period lists everyone on duty in it (`Ravi (Counter 1), Priya (Counter 2)`) rather than blaming whoever closed. Pinning to one person needs one person per period, which the shop decides, not the app.
- **Online only, like the day-end count** (packs are converted on the server). Offline, End shift says the count is skipped; the day-end count still covers the day. **Skip this time** is there for the same reason: the drawer must never be held hostage by the milk count.
- **Its own record, linked to the shift by id with no foreign key:** the tablet may not have sent the shift yet. Counting the same shift again replaces it (a recount, not a new period).
- `POST /handover-counts` (any staff, blind: the answer is only how many items were taken), `GET /reports/handover?business_date=` (owner).

### Also in this phase
- **One migration ties the four open heads together** (`a10c0d1e2f30`) and adds everything above: two columns on `wastage_entries`, the `wastage_status` enum (dropped on downgrade), the shop's limit, and two tables with row-level security. All additive.
- **Demo data:** an afternoon top-up from the local shop (a busy Sunday sold more mango pulp than was bought and the demo test failed on 4 Oct), the odd fridge failure for the owner to judge, and milk and fruit counted at the 3 pm shift change.
- **Bug found by the browser test:** the wastage limit field was reset under the owner's typing whenever Day end refreshed. The limit now loads once; only the list reloads.

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

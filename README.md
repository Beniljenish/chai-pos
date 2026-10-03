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

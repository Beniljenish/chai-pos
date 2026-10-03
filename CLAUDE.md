# chai-pos: guide for Claude sessions

Billing + stock app for tea and juice shops in India. FastAPI + Postgres backend (`backend/`), React PWA (`frontend/`). The living spec is `docs/SPEC.md` (links to the full spec doc); the README has the decisions and trade-offs for every phase. **Read the README section for the area you touch before changing it.**

The owner (Benil) is moving from finance/ops into engineering: explain trade-offs, don't just agree; challenge weak ideas with reasons.

## Run and test

```bash
# Backend (needs Postgres; locally: `service postgresql start`, user/pass chai/chai)
cd backend
export JWT_SECRET=local-test-secret-0123456789abcdef0123
export DATABASE_URL=postgresql+psycopg://chai:chai@localhost:5432/chai_pos_test
ruff format . && ruff check . && pytest -p no:warnings

# Frontend
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs backend (lint, migration round trip + `alembic check`, pytest), frontend, then end-to-end Playwright against a real backend. Screenshots land on the `e2e-screenshots` branch: `git fetch origin e2e-screenshots` and look at them after UI changes. Read failures with `gh api repos/Beniljenish/chai-pos/check-runs/<id>/annotations`.

Local Playwright: `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` with a gitignored `frontend/playwright.local.config.ts` that sets `launchOptions.executablePath`. The day-end spec runs last on purpose (closing a day changes shop-wide state).

## Rules that are not negotiable

- **Money is integer paise; quantities are `NUMERIC(14,3)` in base units (ml, g, piece).** Never floats for either. GST rounding is ROUND_HALF_UP per line, rule shared by `backend/app/services/gst.py` and `frontend/src/lib/gst.ts` and cross-checked by `shared/gst_crosscheck.json`. A ₹20 tea at 5% inclusive is 19.04 + 0.48 + 0.48.
- **Stock is an append-only ledger** (Postgres trigger forbids UPDATE/DELETE). Stock on hand = SUM. Corrections are new rows with a reason.
- **Tenant isolation is automatic** (`backend/app/db/tenancy.py`). Never filter by `shop_id` by hand. Every new route with an `{id}` must be added to `tests/test_tenant_gate.py` (the gate test fails until you do; date-keyed routes go in `DATE_ROUTES` with their own cross-shop test).
- **Every new table needs row-level security** (`ALTER TABLE x ENABLE ROW LEVEL SECURITY` in its migration); `test_database_security.py` fails otherwise. Postgres enum types must be dropped in `downgrade()`.
- **Recipes are immutable versions.** Old bills deduct by the version they were sold under.
- **Bills are written on the device first** and synced idempotently (`POST /sync/bills`). Device and server totals that disagree are accepted and flagged, never rejected.
- **Day-end counts are blind for cashiers** (no expected quantities, no ₹). Owner-only: reports, variance, approval, prices, recipes.
- **Permissions are enforced on the server**, never only hidden in the UI.
- **No secrets in the repo.** They live in Vercel env vars; the owner types passwords and DB URLs himself.

## Workflow

- Branch per change, PR to `main`, CI green before asking to merge. **Never stack PRs** (a PR based on another unmerged branch): after the lower one merges, the upper one merges into a dead branch, not `main`. If stacking is unavoidable, retarget the base to `main` as soon as the lower PR merges.
- Commits end with the attribution lines from the session's instructions.
- Write the test first when fixing a bug, and check a new test fails without the fix (break the code on purpose, then restore).
- After UI changes, look at the CI screenshots at phone width (390 px). The phone top bar has broken twice: tabs + sync badge must stay on one row (an e2e assertion guards it).

## Deploy (staging)

- **Only `main` deploys** (`git.deploymentEnabled` in both `vercel.json`). The Hobby plan allows 100 deployments a day across both projects; branch previews and the CI `e2e-screenshots` pushes used them up on 3 Oct 2026 and the next merge silently did not deploy. If a merge does not deploy, check the count before anything else.
- App: `chai-pos-app.vercel.app` (Vercel project `chai-pos-app`, root `frontend/`). API: `chai-pos-api.vercel.app` (project `chai-pos-api`, root `backend/`, region `icn1`). Both deploy on merge to `main`.
- Database: Supabase project `chai-pos` (ref `dffvdkxprmoxytbbummz`, Seoul), reached through the transaction pooler (`DB_SERVERLESS=true`: NullPool, no prepared statements).
- **Migrations are applied to Supabase by hand, before merging** when they are additive (new tables/columns the live code ignores): render with `alembic upgrade <from>:<to> --sql`, replace `%%` with `%`, drop BEGIN/COMMIT, run inside one transaction via the Supabase connector, then check `alembic_version`, RLS on, and zero `anon`/`authenticated` grants. A migration that removes or renames something needs a two-step deploy; ask first.
- Staging logins are placeholders (owner `9000000001`, cashier `9000000002`); the seeded shop is "Demo Tea Stall (placeholder)".

## Where things are

- `backend/app/services/`: `gst.py`, `billing.py` (sync, stock deduction, late-bill hook), `recipes.py`, `stock.py` (stock-in, openings, batches), `dayend.py` (wastage, counts, variance).
- `backend/app/api/v1/`: one router per area. Schemas in `app/schemas*.py`.
- `frontend/src/lib/`: pure logic with unit tests (gst, billing, sync, qty, recipe, gstin, dayend). `frontend/src/app/`: screens.
- Phase gates and status: `docs/SPEC.md`. Phase 3 gate (variance to the paisa) is `tests/test_phase3_gate.py`.

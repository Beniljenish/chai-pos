# Handoff: where the build stands (4 Oct 2026, end of the unattended session)

For a new Claude Code session picking up chai-pos. Read `CLAUDE.md` first (rules that are not negotiable), then this file, then the README section for whatever you touch.

## State right now

| Thing | State |
| --- | --- |
| `main` | Phases 0–5.4 merged (PRs #24 kitchen + service report, #25 UI polish, #27 Tablets crash fix, #29 parallel migration heads). Deployed on merge. |
| Supabase `alembic_version` | `3e72290e9f62`. Nothing on `main` needs a newer revision. |
| Open PRs, each **with a migration**, waiting for Benil | #26 Razorpay test mode (`59c516ec02c9`), #28 customer messages by iMessage/Inkbox (`feebafd74402`), #30 Phase 6 discounts/split payment/khata/split bill (`159f8fea95a7`), #31 Phase 7 reports/GST summary/purchases (`1dedecb97caa`). CI green on each. |
| Not built (design note only) | Phase 8c: Swiggy/Zomato and multiple outlets (README, "Phase 8c (design only)"). Lands with #31. |

## Order of work (status)

1. Phase 5.3: done (#24). Flaky sales spec fixed in the app (sync badge race).
2. Phase 5.4 UI polish: done (#25). Also found and fixed: sheets losing the cursor on refresh; the Tablets screen crashing when a tablet had waiting bills (#27).
3. Phase 8a Razorpay (test mode): **#26, waiting for Benil** (migration, keys, webhook, one real test payment).
4. Phase 8b iMessage through Inkbox: **#28, waiting for Benil** (migration, API key, decide on a dedicated iMessage line).
5. Phase 6: **#30, waiting for Benil** (migration; CA question on discounts and GST).
6. Phase 7: **#31, waiting for Benil** (migration; accountant to check one month's GST summary).
7. Phase 8c: design note written; not built until the accounts exist.
- Follow-ups noted in the README: keep pay-first takeaway orders on the kitchen screen after settling (Phase 5.3); discounts at the table; B2B invoices; snapshot HSN on bill lines.

## How to land the four open PRs (any order)

`main` now runs Alembic with parallel heads (README, Hosting, "Parallel migrations"), so the four migrations do not depend on each other. For each PR:
1. Apply its SQL (in the PR description) to Supabase in one transaction. **The last line depends on what is already applied:** if `alembic_version` still holds only `3e72290e9f62`, use the `UPDATE` line as written. If any of the other three is already applied, use `INSERT INTO alembic_version (version_num) VALUES ('<this PR's revision>');` instead. `alembic_version` then has one row per applied PR; that is expected.
2. Check RLS is on for the new tables and that `anon`/`authenticated` have no grants.
3. Merge. After the first one, the others will show text conflicts (README sections, `main.py` router list, `config.py` settings, `models/__init__.py`, `styles.css`, `order_cases.json`): ask a Claude session to "merge main into <branch> and resolve". Keep both sides; they are additions. Wait for CI to be green, then merge.

## Waiting for Benil

- **The four PRs above:** apply SQL, then merge (see "How to land").
- **Razorpay (#26):** the code reads `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` from the `chai-pos-api` Vercel project. Create a test-mode webhook to `https://chai-pos-api.vercel.app/api/v1/payments/razorpay/webhook` for `payment.captured` and `payment.failed`. Then make one test payment: on the till pick UPI, tick "Collect through Razorpay", Save and collect, and pay with Razorpay's test UPI id `success@razorpay`. Check that the till says Paid and that Sales lists the payment. This session could not reach Razorpay.
- **Inkbox (#28):** add `INKBOX_API_KEY` (and `INKBOX_IDENTITY_ID` if the key is organisation-wide) to the API project. **Decide on a dedicated Inkbox iMessage line:** on the shared service, only customers who have messaged the shop's identity first can be messaged. Until a key is set, messages are written to Manage → Messages and not sent.
- **Your CA (#30):** is sharing a bill discount across items in proportion to their value, then taxing each item on its reduced amount, how they want GST worked out?
- **Your accountant (#31):** check one month's GST summary and the three CSVs before filing from them.
- Make the repo private, and set up backups (Supabase Pro or a nightly export with its own secrets).
- Upgrade to Vercel Pro and Supabase Pro before real sales.
- Pilot shop details: tables and areas, kitchen setup, printer model, menu language.
- Reset the database password that was exposed earlier, and update `DATABASE_URL` in Vercel.

## Razorpay (test mode)

- The owner has added the **test-mode** keys to the Vercel project `chai-pos-api` himself. Suggested names were `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`; read them from settings with those names and say in the PR which names the code expects, so he can check. **Never put keys in the repo, tests or chat.** Tests mock Razorpay's HTTP calls.
- Shape: settling by "UPI (Razorpay)" or "Card (Razorpay)" needs the internet. The server creates a Razorpay order for the bill total (paise, matching our integer paise), the app opens Razorpay Checkout, and the server **verifies the payment signature** (HMAC-SHA256 with the key secret) before it marks the payment captured. Also add a webhook endpoint (`payment.captured`, `payment.failed`) that checks the `X-Razorpay-Signature` with its own webhook secret (`RAZORPAY_WEBHOOK_SECRET`, which the owner sets).
- A bill is still written on the device first. Offline, staff pick plain Cash/UPI as today. A Razorpay payment is a record linked to the bill (new table `payments`, RLS on, tenant-scoped, idempotent by Razorpay payment id). A bill's total is never changed by a payment; a mismatch is flagged, as with device and server totals.
- Owner sees online payments and their status in the sales report.

## Messages by iMessage (Inkbox)

- The owner wants customer messages (bill receipt link, "your order is ready" for takeaway) sent by **iMessage through Inkbox** for now, and SMS/WhatsApp later.
- The Inkbox connection the owner set up is an MCP connector for Claude chats. The **app** needs Inkbox's own developer API and an API key that the owner adds to Vercel himself. Check Inkbox's API documentation for an iMessage send endpoint before building. If there is no usable app-side API, build a `Messenger` interface with a logging provider (messages appear in an owner "Outbox" screen), and say clearly in the PR what is missing.
- Customer phone numbers are personal data: store them only on the customer/order, never in logs, and only message customers who gave their number for that purpose.

## Rules for working unattended

- **Merging:** merge your own PR when CI is green **and it has no migration**. A PR with a migration must not be merged until the migration has been applied to Supabase by hand (CLAUDE.md, "Deploy"). A cloud session usually has no Supabase access: open the PR, put the rendered SQL in its description, and leave it for the owner. Do not stack PRs on unmerged branches (CLAUDE.md, "Workflow").
- Only `main` deploys (Vercel Hobby: 100 deployments a day across both projects). Do not trigger extra deployments.
- Postgres for tests: if the environment has none, install it (`apt-get install -y postgresql`) and create user and password `chai`/`chai` with database `chai_pos_test`, as in CLAUDE.md.
- Explain trade-offs in the README for each phase, as earlier phases do. The owner wants reasons, not just code.
- When something needs the owner (keys, accounts, Supabase), stop that item, write it down at the top of this file under "Waiting for Benil", and carry on with the next item.


# Handoff: where the build stands (4 Oct 2026)

For a new Claude Code session picking up chai-pos. Read `CLAUDE.md` first (rules that are not negotiable), then this file, then the README section for whatever you touch.

## State right now

| Thing | State |
| --- | --- |
| `main` | `a9b0dee` (PR #23 merged). Deployed: app on chai-pos-app.vercel.app. |
| Supabase `alembic_version` | `3e72290e9f62` (tables and orders). Every migration after this one is **not** on Supabase yet. |
| Phases done | 0–3, 4 (lost-bill detection, printing), 5.1 (order engine, floor setup), 5.2 (Tables screen: KOT, bill at the table, settle, takeaway/delivery), 5.3 (kitchen screen, table-service report; PR #24 merged), 5.4 (UI polish). |
| Phase 5.3 | Reviewed, tested and finished on `kitchen-and-service-report-wip` (kitchen view, owner table-service report, daily email lines). No migration. |
| Flaky `e2e/sales.spec.ts` | Fixed in the app: the sync badge could say "All bills sent" with a bill saved mid-sync still waiting (README, Phase 5.3). Unit tests pin it. |

## Order of work

1. **Phase 5.3** from the WIP branch: kitchen screen (items by KOT, "mark ready" sends a `ready` event), owner report of bills changed after printing and cancelled KOT items (from `order_events`: `changed_after_bill`, `cancellations`), the same lines in the daily email. Fix the flaky sales spec in the same PR or just before it.
2. **Phase 5.4: UI polish pass.** Phone (390 px) and tablet. Consolidate the duplicated `Sheet` components into `app/Sheet.tsx`, consistent empty states and errors, faster flows. Look at the CI screenshots after every UI change.
3. **Phase 8a: Razorpay (test mode).** See below. Done before Phase 6 because the owner asked for it now.
4. **Phase 8b: customer messages by iMessage through Inkbox.** See below.
5. **Phase 6:** discounts (item and bill, owner-set limits, reason), split payment (cash + UPI on one bill), split bill (one order into several invoices), customers (phone, name, visit history), credit/khata (bill on credit, record repayment, outstanding per customer).
6. **Phase 7:** reports and inventory: item-wise and hour-wise sales, GST summary (GSTR-1 style export), stock valuation, reorder levels, suppliers and purchase orders (receive a PO into stock-in).
- Follow-up from 5.3: keep pay-first takeaway orders on the kitchen screen after settling (README, Phase 5.3, "Known limit").
7. **Phase 8c later, needs accounts the owner does not have yet:** Swiggy/Zomato, multiple outlets. Write a short design note in the README; do not build.

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

## Waiting for Benil

- **Customer messages PR (Phase 8b) has a migration (`feebafd74402`, new `messages` table, no phone numbers in it).** Its SQL is in the PR description. **Migration order:** #26 (Razorpay, `59c516ec02c9`) and the messages PR both start from `3e72290e9f62`. Apply and merge one; then the other needs its `down_revision` moved to the first one's revision before its SQL is applied (a one-line change; ask a Claude session to "re-chain the open migration PR onto main"). Then: add `INKBOX_API_KEY` to the `chai-pos-api` Vercel project (and `INKBOX_IDENTITY_ID` if the key is organisation-wide). **Decide on a dedicated Inkbox iMessage line:** on Inkbox's shared service, only customers who have messaged the shop's identity first can be messaged; everyone else shows as Failed on Manage → Messages.

- Make the repo private, and set up backups (Supabase Pro or a nightly export with its own secrets).
- Upgrade to Vercel Pro and Supabase Pro before real sales.
- Pilot shop details: tables and areas, kitchen setup, printer model, menu language.
- Reset the database password that was exposed earlier, and update `DATABASE_URL` in Vercel.

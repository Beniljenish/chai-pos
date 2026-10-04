# Handoff: where the build stands (4 Oct 2026, end of the unattended session)

For a new Claude Code session picking up chai-pos. Read `CLAUDE.md` first (rules that are not negotiable), then this file, then the README section for whatever you touch.

## State right now

| Thing | State |
| --- | --- |
| `main` | Phases 0–7, 8a (Razorpay test mode), 8b (iMessage via Inkbox) merged and deployed. Sync fixes #33, #34 and Razorpay method fix #35 (4 Oct). |
| Supabase `alembic_version` | Four rows, one per parallel head: `59c516ec02c9` (payments), `feebafd74402` (messages), `1dedecb97caa` (Phase 7), `159f8fea95a7` (Phase 6). RLS on and no `anon`/`authenticated` grants on every new table. |
| Open PRs | None. |
| Not built (design note only) | Phase 8c: Swiggy/Zomato and multiple outlets (README, "Phase 8c (design only)"). |

## Order of work (status)

1. Phase 5.3: done (#24).
2. Phase 5.4 UI polish: done (#25, plus the Tablets crash fix #27).
3. Phase 8a Razorpay (test mode): **merged (#26)**. UPI and card each open their own Checkout; the server confirms the payment with Razorpay and captures it. Waiting for one real test payment (below).
4. Phase 8b iMessage through Inkbox: **merged (#28)**. Messages are written to Manage → Messages until an Inkbox key is set.
5. Phase 6: **merged (#30)**. CA question on discounts and GST still open.
6. Phase 7: **merged (#31)**. Accountant to check one month's GST summary.
7. Phase 8c: design note written; not built until the accounts exist.
- Follow-ups noted in the README: keep pay-first takeaway orders on the kitchen screen after settling (Phase 5.3); discounts at the table; B2B invoices; snapshot HSN on bill lines.

## Waiting for Benil

- **Razorpay:** keys and webhook secret are set in the `chai-pos-api` project. In Razorpay's dashboard (test mode), create a webhook to `https://chai-pos-api.vercel.app/api/v1/payments/razorpay/webhook` with events `payment.authorized`, `payment.captured`, `payment.failed` and `order.paid`, using the same secret as `RAZORPAY_WEBHOOK_SECRET`. Then, as owner, open **Manage → Shop & GST → Online payments (Razorpay) → Check connection**: it should say test mode, connected. Then on the till: UPI, tick "Collect through Razorpay", Save and collect, pay with `success@razorpay`; and once more with Card using Razorpay's test card. The till should say Paid each time and Sales should list both payments. This session cannot reach Razorpay.
- **Inkbox:** add `INKBOX_API_KEY` (and `INKBOX_IDENTITY_ID` if the key is organisation-wide) to the API project. **Decide on a dedicated Inkbox iMessage line:** on the shared service, only customers who have messaged the shop's identity first can be messaged.
- **Your CA (#30):** is sharing a bill discount across items in proportion to their value, then taxing each item on its reduced amount, how they want GST worked out?
- **Your accountant (Phase 7):** check one month's GST summary and the three CSVs before filing from them.
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


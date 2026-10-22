# Spec

The living v1 spec is the Claude doc **"Tea & Juice Shop POS — v1 Spec"**:
https://claude.ai/code/artifact/98e95bd1-7f72-49ce-95e8-9daa68b9ed18

It stays the single source of truth; this file only tracks the phase gates.

## Phase gates

| Phase | Scope | Gate (must pass before the next phase) | Status |
| --- | --- | --- | --- |
| 0 | Repo, Docker, CI, auth + roles, shops/users/devices, tenant layer | CI green; cross-shop data-leak test passes | Done |
| 1 | Ingredients, pack units, prep/yield recipes, modifiers, stock-in, ledger | Stock on hand = ledger sum; old bills ignore recipe edits | Done |
| 2 | `/sync/bills` idempotent, GST maths in paise, PWA billing + Dexie outbox | 20 bills offline then online -> 20 rows, 0 duplicates | Done (2a backend, 2b app) |
| 3 | Blind counts, wastage codes, adherence %, shifts + cash, voids, reports | Variance matches a hand-worked sample day to the paise | Done: gate, voids, sales report, staff accounts, shifts + cash |
| 4 | Deploy, backups, printing, 1-week recipe calibration in a real shop | 7 days live, no lost bills | Lost-bill detection and printing done; backups, Pro deploy, pilot week to do |
| 5 | Restaurant service: tables, running orders, KOT, kitchen screen, bill then settle | A table order from two devices settles into one invoice | 5.1 engine and floor setup, 5.2 Tables screen (KOT, bill, settle, takeaway/delivery) done |
| 11 | Food court ordering: customers scan one QR, pick an outlet and order; pay at the counter | A customer's order reaches only its own outlet; nothing of another shop is readable without login | Built, with a super admin who makes courts and adds outlets (migrations 027da6efe82c and b4bb997f2f3c to apply to Supabase by hand); online payment not built |
| 12 | Tamil and English; AI helpers (buy by voice or photo, why the stock is short, ask your shop, dish names in Tamil); speaking tokens aloud; UPI match, a bill's history (bills can no longer be edited), GST limit watch | The model only proposes and explains: a draft is checked in code and saved only by the owner; a bill cannot be edited or deleted in the database | Built and tested with a stand-in model; the real model, Tamil speech and bill photos still to try with a key and a phone (migration f1a5c9d3e446 to apply to Supabase by hand) |
| 13 | Round two: phone codes and forgot-password by code, sign-up limits, outlet statements with the operator's fee, automatic refund of cancelled paid orders, owner helpers (commission calculator, tomorrow's prep, auto sold-out, daily summary), pickup time slots, table QR, food court display board, dish photos from the phone, more Tamil | A code is never stored in clear and is limited by tries and by hour; a fee is worked out per order so a statement adds up to the paisa; a paid order is never turned away over a slot; the board shows tokens only | Built and tested; no real SMS or WhatsApp sender (needs your provider), the daily message goes by the existing iMessage provider (migration a2b6d1f4c557 to apply to Supabase by hand) |
| 10 | v1 gaps: 30-day SOP adherence trend, owner approval for large wastage, shift-level counts for milk and fruit | Shift periods add up to the day's variance to the paisa; a rejected wastage shows as missing | Done |

## Placeholder data

Until the pilot-shop visit, seed data and recipes are placeholders. Everything
seeded is marked "(placeholder)" in its name.

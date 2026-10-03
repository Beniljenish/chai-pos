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
| 5 | Restaurant service: tables, running orders, KOT, kitchen screen, bill then settle | A table order from two devices settles into one invoice | 5.1 engine and floor setup done |

## Placeholder data

Until the pilot-shop visit, seed data and recipes are placeholders. Everything
seeded is marked "(placeholder)" in its name.

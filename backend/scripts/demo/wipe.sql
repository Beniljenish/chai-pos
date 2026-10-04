-- Everything but the shop and its logins (README, "Demo data").
-- TRUNCATE is not stopped by the append-only triggers on the stock ledger and
-- order events (they forbid row UPDATE/DELETE): this is the one place it is used.
TRUNCATE
  stock_ledger, stock_openings, stock_receipts, prep_batches, wastage_entries,
  day_count_lines, day_counts,
  bill_line_modifiers, bill_lines, bill_voids, payments, credit_repayments, bills,
  cash_movements, shifts,
  order_events, orders, dining_tables, dining_areas,
  purchase_order_lines, purchase_orders, suppliers,
  menu_item_modifiers, modifier_lines, modifiers, recipe_lines, recipes, menu_items,
  pack_units, ingredients,
  customers, messages, email_outbox, refresh_tokens, devices;
DELETE FROM users WHERE phone LIKE '90000200__';  -- demo staff from an earlier load

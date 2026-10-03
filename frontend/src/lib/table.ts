/**
 * Table service on the device (README, "Table service"): pure helpers for the
 * Tables screen, tested in table.test.ts. Recording and syncing are in orders.ts.
 */
import { buildLines, priceLines, type CartLine } from './billing';
import type { BillTotals } from './gst';
import { billLines, minutesOpen, type KotLineIn, type LiveOrder, type OrderState } from './orders';
import type { Catalogue, DiningArea, SyncBillLine } from './types';

/**
 * A draft round as KOT lines. Each line freezes the name and price as they are
 * now: if the owner changes the menu while the table eats, the table still pays
 * what it ordered at.
 */
export function kotLinesFromCart(
  cart: (CartLine & { note?: string })[],
  catalogue: Catalogue,
  newId: () => string = () => crypto.randomUUID(),
): KotLineIn[] {
  const built = buildLines(cart, catalogue);
  return built.map((l, i) => ({
    line_id: newId(),
    menu_item_id: l.menu_item_id,
    name: l.name,
    qty: l.qty,
    unit_price_paise: l.unit_price_paise,
    gst_rate_bp: l.gst_rate_bp,
    tax_inclusive: l.tax_inclusive,
    modifiers: l.modifiers,
    note: (cart[i].note ?? '').trim(),
  }));
}

export const recipeFor = (catalogue: Catalogue) => {
  const recipes = new Map(catalogue.menu_items.map((m) => [m.id, m.recipe?.id ?? null]));
  return (menuItemId: string) => recipes.get(menuItemId) ?? null;
};

export interface PricedOrder {
  /** Bill lines for what is still being charged, with their totals filled in. */
  lines: SyncBillLine[];
  /** null when nothing is being charged (every line cancelled, or nothing sent yet). */
  totals: BillTotals | null;
}

/** What the table owes right now, by the same GST rules as a counter bill. */
export function priceOrder(state: OrderState, catalogue: Catalogue): PricedOrder {
  const lines = billLines(state, recipeFor(catalogue));
  if (lines.length === 0) return { lines, totals: null };
  return { lines, totals: priceLines(lines, catalogue.shop.gst_type) };
}

// ---------------------------------------------------------------- the floor
export type TableStatus = 'free' | 'running' | 'billed';

export interface FloorTable {
  id: string;
  name: string;
  seats: number;
  status: TableStatus;
  /** Unfinished orders on this table. Normally one; two tablets offline can make two. */
  orders: LiveOrder[];
  minutes: number;
  totalPaise: number;
  covers: number;
}

export interface FloorArea {
  id: string;
  name: string;
  tables: FloorTable[];
}

export interface Floor {
  areas: FloorArea[];
  /** Takeaway, delivery, and orders whose table was switched off or deleted. */
  other: LiveOrder[];
}

const total = (o: LiveOrder, c: Catalogue) => {
  try {
    return priceOrder(o.state, c).totals?.total ?? 0;
  } catch {
    return 0; // a line the GST rules refuse: shown as 0 here, the order screen says why
  }
};

export function floorModel(catalogue: Catalogue, orders: LiveOrder[], now = Date.now()): Floor {
  const areas: DiningArea[] = (catalogue.areas ?? []).filter((a) => a.is_active);
  const placed = new Set<string>();
  const out: FloorArea[] = areas.map((a) => ({
    id: a.id,
    name: a.name,
    tables: a.tables
      .filter((t) => t.is_active)
      .map((t) => {
        const mine = orders.filter((o) => o.state.table_id === t.id);
        mine.forEach((o) => placed.add(o.id));
        const status: TableStatus =
          mine.length === 0 ? 'free' : mine.every((o) => o.state.status === 'billed') ? 'billed' : 'running';
        return {
          id: t.id,
          name: t.name,
          seats: t.seats,
          status,
          orders: mine,
          minutes: mine.length ? Math.max(...mine.map((o) => minutesOpen(o.state, now))) : 0,
          totalPaise: mine.reduce((n, o) => n + total(o, catalogue), 0),
          covers: mine.reduce((n, o) => n + o.state.covers, 0),
        };
      }),
  }));
  return { areas: out.filter((a) => a.tables.length > 0), other: orders.filter((o) => !placed.has(o.id)) };
}

/** Name of a table by id, from the catalogue ("" when it is gone). */
export function tableName(catalogue: Catalogue, tableId: string | null): string {
  if (!tableId) return '';
  for (const a of catalogue.areas ?? []) for (const t of a.tables) if (t.id === tableId) return t.name;
  return '';
}

/** How an order is named on screen and on paper: "T4", "Takeaway: Priya", "Delivery #C1-3". */
export function orderLabel(catalogue: Catalogue, state: OrderState): string {
  if (state.order_type === 'dine_in') return tableName(catalogue, state.table_id) || 'No table';
  const kind = state.order_type === 'takeaway' ? 'Takeaway' : 'Delivery';
  if (state.customer_name) return `${kind}: ${state.customer_name}`;
  return state.kots[0] ? `${kind} #${state.kots[0].kot_no}` : kind;
}

export const hasTables = (catalogue: Catalogue | null) =>
  Boolean(catalogue?.areas?.some((a) => a.is_active && a.tables.some((t) => t.is_active)));

/** Reasons offered as one tap when a sent item is cancelled (the person can type their own). */
export const CANCEL_REASONS = ['Customer changed mind', 'Wrong item entered', 'Item not available', 'Taking too long'];

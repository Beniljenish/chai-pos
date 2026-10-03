/**
 * Running orders on this device (README, "Restaurant service"). Tested in orders.test.ts.
 *
 * reduce(): an order's state from its events. The same rules are in
 * backend/app/services/orders.py; shared/order_cases.json pins the two together.
 *
 * Every action (open a table, send a KOT, cancel a line, print the bill, settle)
 * is an event written here first, offline if need be, and sent to the server by
 * the sync worker, before bills. What the device shows is the server's events
 * for each open order plus this device's unsent ones, through the same rules,
 * so it never waits for the network.
 */
import type { Api } from './api';
import { businessDate, uuidv7 } from './billing';
import type { PosDB } from './db';

export type OrderType = 'dine_in' | 'takeaway' | 'delivery';
export type OrderStatus = 'open' | 'billed' | 'settled' | 'cancelled';
export type EventKind =
  | 'open'
  | 'kot'
  | 'cancel'
  | 'move'
  | 'details'
  | 'bill_printed'
  | 'ready'
  | 'settle'
  | 'cancel_order';

export interface ModifierSnap {
  modifier_id: string;
  name: string;
  price_delta_paise: number;
  scale_factor: string;
  lines: { ingredient_id: string; qty_delta: string }[];
}

export interface KotLineIn {
  line_id: string;
  menu_item_id: string;
  name: string;
  qty: number;
  unit_price_paise: number;
  gst_rate_bp: number;
  tax_inclusive: boolean;
  modifiers?: ModifierSnap[];
  note?: string;
}

export interface OrderEvent {
  id: string;
  order_id?: string;
  kind: EventKind;
  at: string;
  by: string;
  data: Record<string, unknown>;
}

export interface OrderLine {
  line_id: string;
  kot_no: string;
  menu_item_id: string;
  name: string;
  qty: number;
  cancelled_qty: number;
  unit_price_paise: number;
  gst_rate_bp: number;
  tax_inclusive: boolean;
  modifiers: ModifierSnap[];
  note: string;
  ready: boolean;
  added_after_bill: boolean;
}

export interface OrderState {
  order_type: OrderType;
  table_id: string | null;
  covers: number;
  customer_name: string;
  customer_phone: string;
  note: string;
  status: OrderStatus;
  opened_at: string | null;
  opened_by: string | null;
  lines: OrderLine[];
  kots: { kot_no: string; at: string; by: string; line_ids: string[] }[];
  cancellations: { line_id: string; name: string; qty: number; reason: string; at: string; by: string; after_bill: boolean }[];
  bill_prints: number;
  changed_after_bill: boolean;
  bill_id: string | null;
  settled_at: string | null;
  cancel_reason: string | null;
  last_at: string | null;
}

const FINAL: OrderStatus[] = ['settled', 'cancelled'];

/** "2026-10-04T11:30:00+05:30" -> "2026-10-04T06:00:00Z" (seconds, UTC), as the server writes it. */
export const isoUtc = (at: string) => new Date(at).toISOString().replace(/\.\d{3}Z$/, 'Z');

export function emptyState(): OrderState {
  return {
    order_type: 'dine_in',
    table_id: null,
    covers: 0,
    customer_name: '',
    customer_phone: '',
    note: '',
    status: 'open',
    opened_at: null,
    opened_by: null,
    lines: [],
    kots: [],
    cancellations: [],
    bill_prints: 0,
    changed_after_bill: false,
    bill_id: null,
    settled_at: null,
    cancel_reason: null,
    last_at: null,
  };
}

export function reduce(events: OrderEvent[]): OrderState {
  const s = emptyState();
  let opened = false;
  const sorted = [...events].sort((a, b) => {
    const ta = Date.parse(a.at);
    const tb = Date.parse(b.at);
    return ta !== tb ? ta - tb : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  for (const e of sorted) {
    if (FINAL.includes(s.status)) break;
    const d = (e.data ?? {}) as Record<string, unknown>;
    const at = isoUtc(e.at);
    const by = String(e.by);
    const lines = new Map(s.lines.map((l) => [l.line_id, l]));
    switch (e.kind) {
      case 'open':
        if (opened) continue;
        opened = true;
        s.order_type = (d.order_type as OrderType) ?? 'dine_in';
        s.table_id = (d.table_id as string | null) ?? null;
        s.covers = Number(d.covers ?? 0) || 0;
        s.customer_name = (d.customer_name as string) || '';
        s.customer_phone = (d.customer_phone as string) || '';
        s.note = (d.note as string) || '';
        s.opened_at = at;
        s.opened_by = by;
        break;
      case 'kot': {
        const added: string[] = [];
        for (const ln of (d.lines as KotLineIn[]) ?? []) {
          if (lines.has(ln.line_id)) continue; // the same KOT line twice: kept once
          const row: OrderLine = {
            line_id: ln.line_id,
            kot_no: (d.kot_no as string) ?? '',
            menu_item_id: ln.menu_item_id,
            name: ln.name,
            qty: Number(ln.qty),
            cancelled_qty: 0,
            unit_price_paise: Number(ln.unit_price_paise),
            gst_rate_bp: Number(ln.gst_rate_bp),
            tax_inclusive: Boolean(ln.tax_inclusive),
            modifiers: ln.modifiers ?? [],
            note: ln.note ?? '',
            ready: false,
            added_after_bill: s.bill_prints > 0,
          };
          s.lines.push(row);
          lines.set(row.line_id, row);
          added.push(row.line_id);
        }
        if (added.length) {
          s.kots.push({ kot_no: (d.kot_no as string) ?? '', at, by, line_ids: added });
          if (s.bill_prints > 0) {
            s.changed_after_bill = true;
            s.status = 'open';
          }
        }
        break;
      }
      case 'cancel': {
        const ln = lines.get(d.line_id as string);
        const take = ln ? Math.min(Number(d.qty ?? 0), ln.qty) : 0;
        if (!ln || take <= 0) continue;
        ln.qty -= take;
        ln.cancelled_qty += take;
        const after = s.bill_prints > 0;
        s.cancellations.push({ line_id: ln.line_id, name: ln.name, qty: take, reason: (d.reason as string) || '', at, by, after_bill: after });
        if (after) {
          s.changed_after_bill = true;
          s.status = 'open';
        }
        break;
      }
      case 'move':
        s.table_id = (d.table_id as string | null) ?? null;
        break;
      case 'details':
        if ('covers' in d) s.covers = Number(d.covers ?? 0) || 0;
        for (const k of ['customer_name', 'customer_phone', 'note'] as const) if (k in d) s[k] = (d[k] as string) || '';
        break;
      case 'bill_printed':
        s.bill_prints += 1;
        s.status = 'billed';
        break;
      case 'ready':
        for (const id of (d.line_ids as string[]) ?? []) {
          const ln = lines.get(id);
          if (ln) ln.ready = true;
        }
        break;
      case 'settle':
        s.status = 'settled';
        s.bill_id = (d.bill_id as string) ?? null;
        s.settled_at = at;
        break;
      case 'cancel_order':
        s.status = 'cancelled';
        s.cancel_reason = (d.reason as string) || '';
        break;
      default:
        continue;
    }
    s.last_at = at;
  }
  return s;
}

// ---------------------------------------------------------------- on this device
export interface LiveOrder {
  id: string;
  state: OrderState;
  /** Events this device has not sent yet (so the screen can say "not sent"). */
  unsent: number;
}

/** The server's latest view of one unfinished order (from /orders/live). */
export interface OrderSnapshot {
  id: string;
  status: OrderStatus;
  events: OrderEvent[];
}

async function queue(db: PosDB, ev: OrderEvent & { order_id: string }) {
  const last = await db.orderEvents.orderBy('seq').last();
  await db.orderEvents.add({ id: ev.id, orderId: ev.order_id, seq: (last?.seq ?? 0) + 1, status: 'pending', payload: ev });
}

function event(orderId: string, kind: EventKind, by: string, data: Record<string, unknown>, now: Date): OrderEvent & { order_id: string } {
  return { id: uuidv7(now.getTime()), order_id: orderId, kind, at: now.toISOString(), by, data };
}

export interface OpenInput {
  orderType: OrderType;
  tableId?: string | null;
  covers?: number;
  customerName?: string;
  customerPhone?: string;
  note?: string;
}

export async function openOrder(db: PosDB, input: OpenInput, by: string, now = new Date()): Promise<string> {
  const orderId = uuidv7(now.getTime());
  await queue(
    db,
    event(orderId, 'open', by, {
      order_type: input.orderType,
      table_id: input.tableId ?? null,
      covers: input.covers ?? 0,
      customer_name: input.customerName ?? '',
      customer_phone: input.customerPhone ?? '',
      note: input.note ?? '',
    }, now),
  );
  return orderId;
}

/** The next KOT number on this device today: "C1-7". */
export async function nextKotNo(db: PosDB, deviceId: string, deviceCode: string, now = new Date()): Promise<string> {
  const key = `${deviceId}:kot:${businessDate(now)}`;
  return db.transaction('rw', db.counters, async () => {
    const n = ((await db.counters.get(key))?.lastSeq ?? 0) + 1;
    await db.counters.put({ key, lastSeq: n });
    return `${deviceCode}-${n}`;
  });
}

export async function sendKot(db: PosDB, orderId: string, kotNo: string, lines: KotLineIn[], by: string, now = new Date()) {
  if (lines.length === 0) throw new Error('Nothing to send');
  await queue(db, event(orderId, 'kot', by, { kot_no: kotNo, lines: lines.map((l) => ({ modifiers: [], note: '', ...l })) }, now));
}

export async function act(
  db: PosDB,
  orderId: string,
  kind: Exclude<EventKind, 'open' | 'kot'>,
  data: Record<string, unknown>,
  by: string,
  now = new Date(),
) {
  await queue(db, event(orderId, kind, by, data, now));
}

/** Every unfinished order this device knows about, as it stands right now. */
export async function liveOrders(db: PosDB): Promise<LiveOrder[]> {
  const [snaps, pending] = await Promise.all([db.orders.toArray(), db.orderEvents.where('status').equals('pending').toArray()]);
  const ids = new Set([...snaps.map((s) => s.id), ...pending.map((p) => p.orderId)]);
  const out: LiveOrder[] = [];
  for (const id of ids) {
    const snap = snaps.find((s) => s.id === id);
    const mine = pending.filter((p) => p.orderId === id).map((p) => p.payload);
    const seen = new Set((snap?.events ?? []).map((e) => e.id));
    const state = reduce([...(snap?.events ?? []), ...mine.filter((e) => !seen.has(e.id))]);
    if (!FINAL.includes(state.status) && state.opened_at) out.push({ id, state, unsent: mine.length });
  }
  return out.sort((a, b) => (a.state.opened_at ?? '').localeCompare(b.state.opened_at ?? ''));
}

export async function liveOrder(db: PosDB, id: string): Promise<LiveOrder | undefined> {
  return (await liveOrders(db)).find((o) => o.id === id);
}

// ---------------------------------------------------------------- sync
/** Send pending events, oldest first. Same contract as bills. Returns how many were sent. */
export async function syncOrderEvents(api: Api, db: PosDB, deviceId: string): Promise<number> {
  const batch = await db.orderEvents.where('[status+seq]').between(['pending', -Infinity], ['pending', Infinity]).limit(200).toArray();
  if (batch.length === 0) return 0;
  const { results } = await api.post<{ results: { id: string; status: string; reason: string | null }[] }>('/sync/orders', {
    device_id: deviceId,
    events: batch.map((b) => b.payload),
  });
  await db.transaction('rw', db.orderEvents, async () => {
    for (const r of results) {
      if (r.status === 'accepted' || r.status === 'duplicate') await db.orderEvents.update(r.id, { status: 'synced' });
      else await db.orderEvents.update(r.id, { status: 'rejected', reason: r.reason ?? 'rejected' });
    }
  });
  return batch.length;
}

interface LiveResponse {
  server_time: string;
  orders: { id: string; status: OrderStatus; events: OrderEvent[] | null }[];
}

/** Fetch what other devices did. Finished orders are dropped from this device. */
export async function pullLive(api: Api, db: PosDB): Promise<void> {
  const since = await db.getMeta<string>('ordersSince');
  const res = await api.get<LiveResponse>(`/orders/live${since ? `?since=${encodeURIComponent(since)}` : ''}`);
  const live = res.orders.filter((o) => o.status === 'open' || o.status === 'billed');
  const liveIds = new Set(live.map((o) => o.id));
  await db.transaction('rw', db.orders, db.orderEvents, db.meta, async () => {
    // Anything the server no longer lists as unfinished is finished (or was never ours to show).
    for (const snap of await db.orders.toArray()) if (!liveIds.has(snap.id)) await db.orders.delete(snap.id);
    for (const o of live) await db.orders.put({ id: o.id, status: o.status, events: o.events ?? [] });
    // Sent events of finished orders are no longer needed on this device.
    const finished = res.orders.filter((o) => !liveIds.has(o.id)).map((o) => o.id);
    if (finished.length) await db.orderEvents.where('orderId').anyOf(finished).and((e) => e.status === 'synced').delete();
    await db.setMeta('ordersSince', res.server_time);
  });
}

// ---------------------------------------------------------------- money
/** Order lines still being charged, as bill lines (priced as they were ordered). */
export function billLines(state: OrderState, recipeFor: (menuItemId: string) => string | null) {
  return state.lines
    .filter((l) => l.qty > 0)
    .map((l) => ({
      menu_item_id: l.menu_item_id,
      recipe_id: recipeFor(l.menu_item_id),
      name: l.name,
      unit_price_paise: l.unit_price_paise,
      qty: l.qty,
      gst_rate_bp: l.gst_rate_bp,
      tax_inclusive: l.tax_inclusive,
      modifiers: l.modifiers,
      totals: { gross: 0, taxable: 0, cgst: 0, sgst: 0, total: 0 },
    }));
}

/** Minutes since the order was opened, for the floor view. */
export const minutesOpen = (state: OrderState, now = Date.now()) =>
  state.opened_at ? Math.max(0, Math.floor((now - Date.parse(state.opened_at)) / 60000)) : 0;

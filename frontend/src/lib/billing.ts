/**
 * Making a bill on the tablet. Never touches the network.
 *
 * saveBill() takes the next invoice number AND writes the bill in ONE IndexedDB
 * transaction: if the app crashes half-way, neither happens, so the invoice
 * series can never get a gap or a duplicate from a crash.
 */
import type { LocalBill, PosDB } from './db';
import { computeBill, type GstType } from './gst';
import type { Catalogue, SyncBill, SyncBillLine } from './types';

export const SHOP_TIMEZONE = 'Asia/Kolkata';

/** Shop-local calendar date, e.g. 00:10 IST on the 4th -> "...-04" even though UTC says 3rd. */
export function businessDate(at: Date, timeZone = SHOP_TIMEZONE): string {
  // en-CA formats as YYYY-MM-DD
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(at);
}

/** Indian financial year, April to March: "2026-10-03" -> "26-27", "2027-02-15" -> "26-27". */
export function financialYear(isoDate: string): string {
  const [y, m] = isoDate.split('-').map(Number);
  const start = m >= 4 ? y : y - 1;
  const two = (n: number) => String(n % 100).padStart(2, '0');
  return `${two(start)}-${two(start + 1)}`;
}

export function invoiceNumber(deviceCode: string, fy: string, seq: number): string {
  return `${deviceCode}/${fy}/${String(seq).padStart(6, '0')}`;
}

/**
 * UUIDv7: time-ordered, so bills sort by creation and index well on the server.
 * 48-bit millisecond timestamp, then random bits (RFC 9562).
 */
export function uuidv7(now = Date.now()): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let ts = BigInt(now);
  for (let i = 5; i >= 0; i--) {
    bytes[i] = Number(ts & 0xffn);
    ts >>= 8n;
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x70; // version 7
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export interface CartLine {
  menuItemId: string;
  qty: number;
  modifierIds: string[];
}

export type PaymentMode = 'cash' | 'upi' | 'card';

/** Turn a cart into the exact payload the server expects, with printed totals. */
export function buildLines(cart: CartLine[], catalogue: Catalogue): SyncBillLine[] {
  const items = new Map(catalogue.menu_items.map((m) => [m.id, m]));
  const mods = new Map(catalogue.modifiers.map((m) => [m.id, m]));
  return cart.map((c) => {
    const item = items.get(c.menuItemId);
    if (!item) throw new Error('Item is no longer on the menu');
    return {
      menu_item_id: item.id,
      recipe_id: item.recipe?.id ?? null,
      name: item.name,
      unit_price_paise: item.price_paise,
      qty: c.qty,
      gst_rate_bp: item.gst_rate_bp,
      tax_inclusive: item.tax_inclusive,
      modifiers: c.modifierIds.map((id) => {
        const m = mods.get(id);
        if (!m) throw new Error('Modifier is no longer available');
        return {
          modifier_id: m.id,
          name: m.name,
          price_delta_paise: m.price_delta_paise,
          scale_factor: m.scale_factor,
          lines: m.lines.map((l) => ({ ingredient_id: l.ingredient_id, qty_delta: l.qty_delta })),
        };
      }),
      totals: { gross: 0, taxable: 0, cgst: 0, sgst: 0, total: 0 }, // filled below
    };
  });
}

export function priceLines(lines: SyncBillLine[], gstType: GstType) {
  const totals = computeBill(
    lines.map((l) => ({
      unitPricePaise: l.unit_price_paise,
      qty: l.qty,
      gstRateBp: l.gst_rate_bp,
      taxInclusive: l.tax_inclusive,
      modifierDeltasPaise: l.modifiers.map((m) => m.price_delta_paise),
    })),
    gstType,
  );
  lines.forEach((l, i) => (l.totals = { ...totals.lines[i] }));
  return totals;
}

export interface SaveBillInput {
  db: PosDB;
  deviceId: string;
  deviceCode: string;
  catalogue: Catalogue;
  cart: CartLine[];
  paymentMode: PaymentMode;
  now?: Date;
}

export async function saveBill(input: SaveBillInput): Promise<LocalBill> {
  const { db, deviceId, deviceCode, catalogue, cart, paymentMode } = input;
  if (cart.length === 0) throw new Error('The bill is empty');
  const now = input.now ?? new Date();
  const bdate = businessDate(now);
  const fy = financialYear(bdate);
  const gstType = catalogue.shop.gst_type;
  const lines = buildLines(cart, catalogue);
  const totals = priceLines(lines, gstType);

  return db.transaction('rw', db.counters, db.bills, async () => {
    const key = `${deviceId}:${fy}`;
    const seq = ((await db.counters.get(key))?.lastSeq ?? 0) + 1;
    await db.counters.put({ key, lastSeq: seq });

    const payload: SyncBill = {
      id: uuidv7(now.getTime()),
      local_seq: seq,
      invoice_no: invoiceNumber(deviceCode, fy, seq),
      sold_at: now.toISOString(),
      payment_mode: paymentMode,
      gst_type: gstType,
      lines,
      totals: {
        taxable: totals.taxable,
        cgst: totals.cgst,
        sgst: totals.sgst,
        subtotal: totals.subtotal,
        round_off: totals.roundOff,
        total: totals.total,
      },
    };
    const bill: LocalBill = {
      id: payload.id,
      seq,
      fy,
      invoiceNo: payload.invoice_no,
      soldAt: payload.sold_at,
      businessDate: bdate,
      totalPaise: totals.total,
      status: 'pending',
      payload,
    };
    await db.bills.add(bill);
    return bill;
  });
}

/**
 * After a storage wipe the local counter restarts at 0. The server knows the
 * highest number it has accepted from this device; never go below it.
 */
export async function resumeCounters(
  db: PosDB,
  deviceId: string,
  lastSeqByFy: Record<string, number>,
): Promise<void> {
  await db.transaction('rw', db.counters, async () => {
    for (const [fy, serverSeq] of Object.entries(lastSeqByFy)) {
      const key = `${deviceId}:${fy}`;
      const local = (await db.counters.get(key))?.lastSeq ?? 0;
      if (serverSeq > local) await db.counters.put({ key, lastSeq: serverSeq });
    }
  });
}

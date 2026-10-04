/**
 * Making a bill on the tablet. Never touches the network.
 *
 * saveBill() takes the next invoice number AND writes the bill in ONE IndexedDB
 * transaction: if the app crashes half-way, neither happens, so the invoice
 * series can never get a gap or a duplicate from a crash.
 */
import type { LocalBill, PosDB } from './db';
import { computeBill, type GstType } from './gst';
import type { BillCustomer, Catalogue, PaymentPart, PayMode, SyncBill, SyncBillLine } from './types';

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
  /** Phase 6: taken off this line, in paise. */
  discountPaise?: number;
}

export type PaymentMode = PayMode;

/**
 * May this person give this discount? The owner sets the most a cashier may take
 * off (basis points of the bill's value); the owner has no limit. The server
 * checks the same rule and flags a bill that got past it (README, Phase 6).
 */
export function discountAllowed(a: { discountPaise: number; grossPaise: number; maxBp: number; isOwner: boolean }): boolean {
  return a.isOwner || a.discountPaise * 10_000 <= a.maxBp * a.grossPaise;
}

/** A percentage of an amount in whole paise, half up (12.5% of 40 = 5). */
export function percentOff(percent: number, paise: number): number {
  return Math.floor((Math.round(percent * 100) * paise + 5_000) / 10_000);
}

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
      ...(c.discountPaise ? { discount_paise: c.discountPaise } : {}),
      totals: { gross: 0, taxable: 0, cgst: 0, sgst: 0, total: 0 }, // filled below
    };
  });
}

/**
 * Price lines with the shared GST rule, writing each line's printed totals. A
 * discount appears in the totals only when there is one, so an undiscounted bill
 * sends exactly what it did before Phase 6.
 */
export function priceLines(lines: SyncBillLine[], gstType: GstType, billDiscountPaise = 0) {
  const totals = computeBill(
    lines.map((l) => ({
      unitPricePaise: l.unit_price_paise,
      qty: l.qty,
      gstRateBp: l.gst_rate_bp,
      taxInclusive: l.tax_inclusive,
      modifierDeltasPaise: l.modifiers.map((m) => m.price_delta_paise),
      discountPaise: l.discount_paise ?? 0,
    })),
    gstType,
    billDiscountPaise,
  );
  lines.forEach((l, i) => {
    const { discount, ...rest } = totals.lines[i];
    l.totals = discount ? { ...rest, discount } : rest;
  });
  return totals;
}

export interface SaveBillInput {
  db: PosDB;
  deviceId: string;
  deviceCode: string;
  catalogue: Catalogue;
  cart: CartLine[];
  paymentMode: PaymentMode;
  /** The logged-in person: the bill is theirs even if it syncs after they log out. */
  cashierId?: string;
  /** The drawer shift open on this tablet, so the cash is checked against it. */
  shiftId?: string;
  /** Settling a table order: its lines (priced when they were ordered) and its id. */
  lines?: SyncBillLine[];
  orderId?: string;
  /** Split bill: which part of the order this invoice is (1 when not split). */
  orderPart?: number;
  /** Phase 6: a discount on the whole bill, and why (any discount needs a reason). */
  billDiscountPaise?: number;
  discountReason?: string;
  /** Split payment or part on credit: must add up to the total. */
  paymentParts?: PaymentPart[];
  /** Whose bill it is (needed for credit). */
  customer?: BillCustomer;
  now?: Date;
}

export async function saveBill(input: SaveBillInput): Promise<LocalBill> {
  const { db, deviceId, deviceCode, catalogue, cart, paymentMode, cashierId, shiftId, orderId } = input;
  if (cart.length === 0 && !input.lines?.length) throw new Error('The bill is empty');
  const now = input.now ?? new Date();
  const bdate = businessDate(now);
  const fy = financialYear(bdate);
  const gstType = catalogue.shop.gst_type;
  const lines = input.lines ? input.lines.map((l) => ({ ...l, totals: { ...l.totals } })) : buildLines(cart, catalogue);
  const billDiscount = input.billDiscountPaise ?? 0;
  const totals = priceLines(lines, gstType, billDiscount);
  const parts = input.paymentParts?.length ? input.paymentParts : undefined;
  if (parts && parts.reduce((a, p) => a + p.paise, 0) !== totals.total) {
    throw new Error('The payment parts do not add up to the bill');
  }
  const onCredit = paymentMode === 'credit' || parts?.some((p) => p.mode === 'credit');
  if (onCredit && !input.customer) throw new Error('A bill on credit needs the customer');

  return db.transaction('rw', db.counters, db.bills, async () => {
    const key = `${deviceId}:${fy}`;
    const seq = ((await db.counters.get(key))?.lastSeq ?? 0) + 1;
    await db.counters.put({ key, lastSeq: seq });

    const payload: SyncBill = {
      id: uuidv7(now.getTime()),
      ...(cashierId ? { cashier_id: cashierId } : {}),
      ...(shiftId ? { shift_id: shiftId } : {}),
      ...(orderId ? { order_id: orderId } : {}),
      ...(input.orderPart && input.orderPart > 1 ? { order_part: input.orderPart } : {}),
      ...(billDiscount ? { bill_discount_paise: billDiscount } : {}),
      ...(totals.discount && input.discountReason ? { discount_reason: input.discountReason } : {}),
      ...(parts ? { payment_parts: parts } : {}),
      ...(input.customer ? { customer: input.customer } : {}),
      local_seq: seq,
      invoice_no: invoiceNumber(deviceCode, fy, seq),
      sold_at: now.toISOString(),
      payment_mode: paymentMode,
      gst_type: gstType,
      lines,
      totals: {
        ...(totals.discount ? { discount: totals.discount } : {}),
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

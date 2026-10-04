/**
 * GST for one bill: the TypeScript twin of backend/app/services/gst.py.
 *
 * Both implementations must pass shared/gst_cases.json. If you change a rule
 * here, change it there too (and the other way round).
 *
 * All money is integer paise. All arithmetic is BigInt: JavaScript's normal
 * numbers are floating point (0.1 + 0.2 !== 0.3), and even Math.floor(a / b)
 * can be off by one for large values. BigInt division is exact.
 */

export type GstType = 'regular' | 'composition' | 'unregistered';

export interface LineIn {
  unitPricePaise: number;
  qty: number;
  gstRateBp: number; // 500 = 5%
  taxInclusive: boolean;
  modifierDeltasPaise?: number[];
  /** Taken off this line by the cashier (Phase 6). */
  discountPaise?: number;
}

export interface LineTotals {
  gross: number;
  /** This line's discount plus its share of the bill discount. */
  discount: number;
  taxable: number;
  cgst: number;
  sgst: number;
  total: number;
}

export interface BillTotals {
  lines: LineTotals[];
  discount: number;
  taxable: number;
  cgst: number;
  sgst: number;
  subtotal: number;
  roundOff: number;
  total: number;
}

export class GstError extends Error {}

const MAX_RATE_BP = 4000; // 40%, the highest GST slab since 22 Sep 2025
const BP = 10_000n;

/** Round-half-up division for non-negative integers: (2n + d) / 2d, truncated. */
function divHalfUp(n: bigint, d: bigint): bigint {
  return (2n * n + d) / (2n * d);
}

function checkInt(name: string, v: number) {
  if (!Number.isSafeInteger(v)) throw new GstError(`${name} must be a whole number`);
}

function validate(line: LineIn): number {
  checkInt('Quantity', line.qty);
  checkInt('Price', line.unitPricePaise);
  checkInt('GST rate', line.gstRateBp);
  if (line.qty <= 0) throw new GstError('Quantity must be at least 1');
  if (line.unitPricePaise < 0) throw new GstError('Price cannot be negative');
  if (line.gstRateBp < 0 || line.gstRateBp > MAX_RATE_BP) {
    throw new GstError(`GST rate must be between 0 and ${MAX_RATE_BP} basis points`);
  }
  const deltas = line.modifierDeltasPaise ?? [];
  deltas.forEach((d) => checkInt('Modifier price', d));
  const unit = line.unitPricePaise + deltas.reduce((a, b) => a + b, 0);
  if (unit < 0) throw new GstError('Price after modifiers cannot be negative');
  const off = line.discountPaise ?? 0;
  checkInt('Discount', off);
  if (off < 0 || off > unit * line.qty) throw new GstError("A line discount must be between nothing and the line's price");
  return unit;
}

/**
 * Split a bill discount across lines in proportion to `amounts`. Largest
 * remainder, ties to the earlier line: the same rule as gst.py share_discount.
 */
export function shareDiscount(discount: number, amounts: number[]): number[] {
  checkInt('Discount', discount);
  if (discount === 0) return amounts.map(() => 0);
  const whole = amounts.reduce((a, b) => a + b, 0);
  if (discount < 0 || discount > whole) throw new GstError('A bill discount must be between nothing and the bill');
  const d = BigInt(discount);
  const w = BigInt(whole);
  const shares = amounts.map((a) => (d * BigInt(a)) / w);
  const rest = amounts.map((a) => (d * BigInt(a)) % w);
  let left = d - shares.reduce((a, b) => a + b, 0n);
  const order = amounts.map((_, i) => i).sort((i, j) => (rest[j] > rest[i] ? 1 : rest[j] < rest[i] ? -1 : i - j));
  for (const i of order) {
    if (left === 0n) break;
    shares[i] += 1n;
    left -= 1n;
  }
  return shares.map(Number);
}

export function computeLine(line: LineIn, gstType: GstType, billShare = 0): LineTotals {
  const gross = BigInt(validate(line)) * BigInt(line.qty);
  const n = (x: bigint) => Number(x);
  const discount = BigInt((line.discountPaise ?? 0) + billShare);
  const net = gross - discount; // what GST is charged on (or included in)

  if (gstType !== 'regular' || line.gstRateBp === 0) {
    return { gross: n(gross), discount: n(discount), taxable: n(net), cgst: 0, sgst: 0, total: n(net) };
  }

  const rate = BigInt(line.gstRateBp);
  // CGST/SGST are each half the rate: taxable x (rate/2) / 10000 = taxable x rate / 20000
  const halfTax = (taxable: bigint) => divHalfUp(taxable * rate, 2n * BP);

  if (line.taxInclusive) {
    const firstTaxable = divHalfUp(net * BP, BP + rate);
    const cgst = halfTax(firstTaxable);
    // The customer pays exactly what is left: taxable absorbs any rounding paise.
    const taxable = net - 2n * cgst;
    return { gross: n(gross), discount: n(discount), taxable: n(taxable), cgst: n(cgst), sgst: n(cgst), total: n(net) };
  }

  const cgst = halfTax(net);
  return {
    gross: n(gross),
    discount: n(discount),
    taxable: n(net),
    cgst: n(cgst),
    sgst: n(cgst),
    total: n(net + 2n * cgst),
  };
}

export function computeBill(lines: LineIn[], gstType: GstType, billDiscountPaise = 0): BillTotals {
  if (lines.length === 0) throw new GstError('A bill needs at least one line');
  const left = lines.map((l) => validate(l) * l.qty - (l.discountPaise ?? 0));
  const shares = shareDiscount(billDiscountPaise, left);
  const computed = lines.map((l, i) => computeLine(l, gstType, shares[i]));
  const sum = (f: (lt: LineTotals) => number) => computed.reduce((a, lt) => a + f(lt), 0);
  const subtotal = sum((lt) => lt.total);
  const total = Number(divHalfUp(BigInt(subtotal), 100n)) * 100; // nearest rupee, half up
  return {
    lines: computed,
    discount: sum((lt) => lt.discount),
    taxable: sum((lt) => lt.taxable),
    cgst: sum((lt) => lt.cgst),
    sgst: sum((lt) => lt.sgst),
    subtotal,
    roundOff: total - subtotal,
    total,
  };
}

/** Rupees for display: 2050 -> "₹20.50", 2000 -> "₹20". */
export function formatRupees(paise: number): string {
  const sign = paise < 0 ? '-' : '';
  const abs = Math.abs(paise);
  const rupees = Math.floor(abs / 100);
  const p = abs % 100;
  return `${sign}₹${rupees.toLocaleString('en-IN')}${p ? '.' + String(p).padStart(2, '0') : ''}`;
}

export interface RateGroup {
  rateBp: number;
  taxable: number;
  cgst: number;
  sgst: number;
}

/** Tax invoices must state the rate, not just the amount; a bill can mix 5% and 18% items. */
export function taxByRate(lines: { gst_rate_bp: number; totals: { taxable: number; cgst: number; sgst: number } }[]): RateGroup[] {
  const groups = new Map<number, RateGroup>();
  for (const l of lines) {
    const g = groups.get(l.gst_rate_bp) ?? { rateBp: l.gst_rate_bp, taxable: 0, cgst: 0, sgst: 0 };
    g.taxable += l.totals.taxable;
    g.cgst += l.totals.cgst;
    g.sgst += l.totals.sgst;
    groups.set(l.gst_rate_bp, g);
  }
  return [...groups.values()].filter((g) => g.cgst + g.sgst > 0).sort((a, b) => a.rateBp - b.rateBp);
}

/** 250 bp (half of 5%) -> "2.5%". */
export function formatRate(bp: number): string {
  return `${Number((bp / 100).toFixed(2))}%`;
}

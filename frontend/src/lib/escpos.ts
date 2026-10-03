/**
 * The receipt in ESC/POS, the command language of almost every thermal receipt
 * printer (README, "Printing"). Tested byte by byte in escpos.test.ts.
 *
 * Two steps, both pure:
 *   receiptRows(): what to print, as rows of plain ASCII text with a style,
 *                  laid out for the paper width (32 characters on 58 mm, 48 on 80 mm)
 *   encode():      those rows as ESC/POS bytes
 *
 * Cheap printers print only their built-in code page, so text is reduced to
 * ASCII: the rupee sign becomes "Rs." and other characters become "?". A shop
 * whose menu is in Tamil or Hindi would need the receipt printed as an image;
 * that is a later step if the pilot shop needs it.
 */
import { formatRate, taxByRate } from './gst';
import type { LocalBill } from './db';
import type { Catalogue, SyncBill, SyncBillLine } from './types';

export type PaperWidth = 32 | 48;

export interface Row {
  text: string;
  align?: 'left' | 'center';
  bold?: boolean;
  big?: boolean; // double width and height: half as many characters fit
}

const TITLES = { regular: 'TAX INVOICE', composition: 'BILL OF SUPPLY', unregistered: 'BILL' } as const;
export const PAYMENT: Record<string, string> = { cash: 'Cash', upi: 'UPI', card: 'Card', split: 'Split', credit: 'Credit' };

/**
 * How the bill was paid, as receipt rows: one row for a single mode, one per part
 * for a split payment. Credit is labelled as owed by the customer (Phase 6).
 */
export function paymentRows(p: SyncBill): [string, number][] {
  const parts = p.payment_parts?.length ? p.payment_parts : [{ mode: p.payment_mode, paise: p.totals.total }];
  return parts.map((x) => [x.mode === 'credit' ? 'On credit (khata)' : `Paid by ${PAYMENT[x.mode] ?? x.mode}`, x.paise]);
}

/** Paise as "Rs.19.04" / "Rs.20" (whole rupees drop the paise, as on screen). */
export function rs(paise: number): string {
  const sign = paise < 0 ? '-' : '';
  const abs = Math.abs(paise);
  const r = Math.floor(abs / 100);
  const p = abs % 100;
  return `${sign}Rs.${r.toLocaleString('en-IN')}${p ? '.' + String(p).padStart(2, '0') : ''}`;
}

/** Only what every printer's code page has: printable ASCII. */
export function ascii(s: string): string {
  return s
    .replace(/₹/g, 'Rs.')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, '-')
    .replace(/×/g, 'x')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '') // é -> e
    .replace(/[^\x20-\x7e]/g, '?');
}

/** Wrap at word boundaries; a word longer than the width is cut. */
export function wrap(text: string, width: number): string[] {
  const out: string[] = [];
  let line = '';
  for (const word of ascii(text).split(/\s+/).filter(Boolean)) {
    let w = word;
    while (w.length > width) {
      if (line) out.push(line), (line = '');
      out.push(w.slice(0, width));
      w = w.slice(width);
    }
    if (!line) line = w;
    else if (line.length + 1 + w.length <= width) line += ' ' + w;
    else out.push(line), (line = w);
  }
  if (line) out.push(line);
  return out.length ? out : [''];
}

/** "Label ........ value" on one line; the label is cut if both do not fit. */
export function leftRight(left: string, right: string, width: number): string {
  const r = ascii(right);
  const l = ascii(left).slice(0, Math.max(0, width - r.length - 1));
  return l + ' '.repeat(Math.max(1, width - l.length - r.length)) + r;
}

function istDateTime(iso: string): string {
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(new Date(iso));
}

export function receiptRows(
  bill: LocalBill,
  shop: Catalogue['shop'],
  width: PaperWidth,
  opts: { voided?: boolean; reprint?: boolean } = {},
): Row[] {
  const p = bill.payload;
  const rows: Row[] = [];
  const line = (text: string, extra: Partial<Row> = {}) => rows.push({ text, ...extra });
  const rule = () => line('-'.repeat(width));
  const half = width / 2; // characters per line in big text

  if (opts.voided) line('*** VOIDED: NOT A VALID BILL ***'.slice(0, width), { align: 'center', bold: true });
  for (const t of wrap(shop.name, half)) line(t, { align: 'center', big: true });
  if (shop.address) for (const t of wrap(shop.address, width)) line(t, { align: 'center' });
  if (p.gst_type !== 'unregistered' && shop.gstin) line(`GSTIN ${shop.gstin}`, { align: 'center' });
  line(TITLES[p.gst_type], { align: 'center', bold: true });
  if (p.gst_type === 'composition')
    for (const t of wrap('Composition taxable person, not eligible to collect tax on supplies', width))
      line(t, { align: 'center' });
  if (opts.reprint) line('(Reprint)', { align: 'center' });
  rule();
  line(leftRight('No.', bill.invoiceNo, width));
  line(leftRight('Date', istDateTime(bill.soldAt), width));
  rule();

  for (const l of p.lines) {
    const mods = l.modifiers.length ? ` (${l.modifiers.map((m) => m.name).join(', ')})` : '';
    for (const t of wrap(l.name + mods, width)) line(t);
    const each = l.unit_price_paise + l.modifiers.reduce((a, m) => a + m.price_delta_paise, 0);
    // With a discount, lines show their full price and the discount gets its own row.
    line(leftRight(`  ${l.qty} x ${rs(each)}`, rs(p.totals.discount ? l.totals.gross : l.totals.total), width));
  }
  rule();
  if (p.totals.discount) {
    const why = p.discount_reason ? ` (${p.discount_reason})` : '';
    for (const t of wrap(`Discount${why}`, width - 10).slice(0, -1)) line(t);
    const last = wrap(`Discount${why}`, width - 10).slice(-1)[0];
    line(leftRight(last, `-${rs(p.totals.discount)}`, width));
  }

  if (p.gst_type === 'regular' && p.totals.cgst > 0) {
    line(leftRight('Taxable value', rs(p.totals.taxable), width));
    for (const g of taxByRate(p.lines)) {
      line(leftRight(`CGST @${formatRate(g.rateBp / 2)}`, rs(g.cgst), width));
      line(leftRight(`SGST @${formatRate(g.rateBp / 2)}`, rs(g.sgst), width));
    }
  }
  if (p.totals.round_off !== 0) line(leftRight('Round off', rs(p.totals.round_off), width));
  line(leftRight('TOTAL', rs(p.totals.total), half), { big: true, bold: true });
  if (p.payment_parts?.length) for (const [label, paise] of paymentRows(p)) line(leftRight(label, rs(paise), width));
  else line(leftRight('Paid by', p.payment_mode === 'credit' ? 'Credit (khata)' : PAYMENT[p.payment_mode], width));
  if (p.customer?.name) line(leftRight('Customer', p.customer.name, width));
  rule();
  line('Thank you', { align: 'center' });
  return rows.map((r) => ({ ...r, text: ascii(r.text) }));
}

// ---------------------------------------------------------------- table service
export interface KotTicket {
  /** "KOT" for a new round; "CANCEL" tells the kitchen to stop making something. */
  kind: 'KOT' | 'CANCEL';
  kotNo: string;
  /** "T4", "Takeaway: Priya". */
  label: string;
  at: string;
  byName: string;
  covers?: number;
  lines: { name: string; qty: number; modifiers?: { name: string }[]; note?: string }[];
  reason?: string;
}

/** The kitchen ticket: no prices, big table name, quantity first. */
export function kotRows(t: KotTicket, width: PaperWidth): Row[] {
  const rows: Row[] = [];
  const line = (text: string, extra: Partial<Row> = {}) => rows.push({ text, ...extra });
  const half = width / 2;
  line(t.kind === 'CANCEL' ? `CANCEL ${t.kotNo}` : `KOT ${t.kotNo}`, { align: 'center', big: true, bold: true });
  for (const s of wrap(t.label, half)) line(s, { align: 'center', big: true });
  line('-'.repeat(width));
  line(leftRight(istDateTime(t.at), t.byName, width));
  if (t.covers) line(`Guests: ${t.covers}`);
  line('-'.repeat(width));
  for (const l of t.lines) {
    const qty = `${t.kind === 'CANCEL' ? '-' : ''}${l.qty}`.padEnd(4);
    const [first, ...rest] = wrap(l.name, width - 4);
    line(qty + first, { bold: true });
    for (const r of rest) line('    ' + r, { bold: true });
    if (l.modifiers?.length) for (const r of wrap('+ ' + l.modifiers.map((m) => m.name).join(', '), width - 4)) line('    ' + r);
    if (l.note) for (const r of wrap('* ' + l.note, width - 4)) line('    ' + r);
  }
  if (t.reason) {
    line('-'.repeat(width));
    for (const r of wrap(`Reason: ${t.reason}`, width)) line(r);
  }
  return rows.map((r) => ({ ...r, text: ascii(r.text) }));
}

export interface BillSummary {
  label: string;
  covers: number;
  at: string;
  /** Printed more than once: the copy says so, so a second paper bill is not mistaken for a new order. */
  copy: number;
  gstType: Catalogue['shop']['gst_type'];
  lines: SyncBillLine[];
  totals: { taxable: number; cgst: number; sgst: number; roundOff: number; total: number };
}

/**
 * The bill brought to the table before payment. It has no invoice number: the
 * tax invoice is made when the table pays (invoice numbers must have no gaps, and
 * a table that adds a dessert after seeing the bill would otherwise burn one).
 */
export function billSummaryRows(b: BillSummary, shop: Catalogue['shop'], width: PaperWidth): Row[] {
  const rows: Row[] = [];
  const line = (text: string, extra: Partial<Row> = {}) => rows.push({ text, ...extra });
  const rule = () => line('-'.repeat(width));
  const half = width / 2;
  for (const t of wrap(shop.name, half)) line(t, { align: 'center', big: true });
  if (shop.address) for (const t of wrap(shop.address, width)) line(t, { align: 'center' });
  line('BILL', { align: 'center', bold: true });
  if (b.copy > 1) line(`(Copy ${b.copy})`, { align: 'center' });
  rule();
  line(leftRight(b.label, b.covers ? `Guests ${b.covers}` : '', width));
  line(leftRight('Date', istDateTime(b.at), width));
  rule();
  for (const l of b.lines) {
    const mods = l.modifiers.length ? ` (${l.modifiers.map((m) => m.name).join(', ')})` : '';
    for (const t of wrap(l.name + mods, width)) line(t);
    const each = l.unit_price_paise + l.modifiers.reduce((a, m) => a + m.price_delta_paise, 0);
    line(leftRight(`  ${l.qty} x ${rs(each)}`, rs(l.totals.total), width));
  }
  rule();
  if (b.gstType === 'regular' && b.totals.cgst > 0) {
    line(leftRight('Taxable value', rs(b.totals.taxable), width));
    for (const g of taxByRate(b.lines)) {
      line(leftRight(`CGST @${formatRate(g.rateBp / 2)}`, rs(g.cgst), width));
      line(leftRight(`SGST @${formatRate(g.rateBp / 2)}`, rs(g.sgst), width));
    }
  }
  if (b.totals.roundOff !== 0) line(leftRight('Round off', rs(b.totals.roundOff), width));
  line(leftRight('TOTAL', rs(b.totals.total), half), { big: true, bold: true });
  rule();
  for (const t of wrap('Please pay at the counter. Your receipt is printed on payment.', width)) line(t, { align: 'center' });
  return rows.map((r) => ({ ...r, text: ascii(r.text) }));
}

// ---------------------------------------------------------------- bytes
const ESC = 0x1b;
const GS = 0x1d;
const LF = 0x0a;

export const CMD = {
  init: [ESC, 0x40], // ESC @: reset the printer
  alignLeft: [ESC, 0x61, 0],
  alignCenter: [ESC, 0x61, 1],
  boldOn: [ESC, 0x45, 1],
  boldOff: [ESC, 0x45, 0],
  sizeNormal: [GS, 0x21, 0x00],
  sizeBig: [GS, 0x21, 0x11], // double width and double height
  feed: (n: number) => [ESC, 0x64, n], // ESC d n: feed n lines
  cut: [GS, 0x56, 0x42, 0x00], // GS V B 0: feed to the cutter and cut (ignored without one)
};

export function encode(rows: Row[]): Uint8Array {
  const out: number[] = [...CMD.init];
  for (const r of rows) {
    out.push(...(r.align === 'center' ? CMD.alignCenter : CMD.alignLeft));
    out.push(...(r.bold ? CMD.boldOn : CMD.boldOff));
    out.push(...(r.big ? CMD.sizeBig : CMD.sizeNormal));
    for (const ch of r.text) out.push(ch.charCodeAt(0));
    out.push(LF);
  }
  out.push(...CMD.sizeNormal, ...CMD.boldOff, ...CMD.alignLeft, ...CMD.feed(3), ...CMD.cut);
  return Uint8Array.from(out);
}

/** A short receipt to check the printer and paper width from the settings. */
export function testRows(width: PaperWidth): Row[] {
  const rows: Row[] = [
    { text: 'TEST PRINT', align: 'center', big: true },
    { text: '-'.repeat(width) },
    { text: leftRight('Paper width', `${width} characters`, width) },
    { text: '1234567890'.repeat(5).slice(0, width) },
    { text: leftRight('Left', 'Right', width) },
    { text: 'If the line of digits above fits on one line, the width is right.' },
  ];
  return rows.flatMap((r) => (r.text.length > width ? wrap(r.text, width).map((t) => ({ ...r, text: t })) : [r]));
}

/** Base64 of the bytes, for apps that take the receipt as a link (RawBT). */
export function toBase64(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

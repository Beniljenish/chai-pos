import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import { saveBill } from './billing';
import { PosDB } from './db';
import { CMD, ascii, encode, leftRight, receiptRows, rs, testRows, toBase64, wrap } from './escpos';
import { testCatalogue } from './test-fixtures';
import type { Catalogue } from './types';

let db: PosDB;
beforeEach(() => {
  db = new PosDB(`escpos-${Math.random()}`);
});

const shop: Catalogue['shop'] = {
  ...testCatalogue.shop,
  name: 'Ravi Tea Stall',
  address: '12, Gandhi Road, Tiruchirappalli 620001',
  gstin: '33ABCDE1234F1Z7',
};

const bill = (cart: { menuItemId: string; qty: number; modifierIds: string[] }[], gst = shop.gst_type) =>
  saveBill({
    db,
    deviceId: 'dev',
    deviceCode: 'C1',
    catalogue: { ...testCatalogue, shop: { ...shop, gst_type: gst } },
    cart,
    paymentMode: 'upi',
    now: new Date('2026-10-04T03:05:00Z'), // 8:35 am IST
  });

describe('text helpers', () => {
  it('money in ASCII', () => {
    expect([rs(2000), rs(1904), rs(48), rs(-2), rs(1234500)]).toEqual([
      'Rs.20',
      'Rs.19.04',
      'Rs.0.48',
      '-Rs.0.02',
      'Rs.12,345',
    ]);
  });
  it('reduces text to what any printer can print', () => {
    expect(ascii('₹20 × 2 – café “chai”')).toBe('Rs.20 x 2 - cafe "chai"');
    expect(ascii('இஞ்சி டீ')).toMatch(/^[?\s]+$/); // Tamil: not in the printer's code page
  });
  it('wraps at words and cuts words longer than the line', () => {
    expect(wrap('Masala tea with extra ginger', 12)).toEqual(['Masala tea', 'with extra', 'ginger']);
    expect(wrap('Supercalifragilistic', 8)).toEqual(['Supercal', 'ifragili', 'stic']);
  });
  it('puts a value on the right edge', () => {
    expect(leftRight('TOTAL', 'Rs.20', 16)).toBe('TOTAL      Rs.20');
    expect(leftRight('A very long label indeed', 'Rs.20', 16)).toBe('A very lon Rs.20'); // 16 exactly
  });
});

describe('the receipt, 58 mm (32 characters)', () => {
  it('matches the screen receipt: GST maths, rates, total, payment', async () => {
    const b = await bill([{ menuItemId: 'tea', qty: 1, modifierIds: [] }]);
    const rows = receiptRows(b, shop, 32);
    const text = rows.map((r) => r.text);
    expect(text).toEqual([
      'Ravi Tea Stall',
      '12, Gandhi Road, Tiruchirappalli',
      '620001',
      'GSTIN 33ABCDE1234F1Z7',
      'TAX INVOICE',
      '-'.repeat(32),
      'No.              C1/26-27/000001',
      'Date       04 Oct 2026, 08:35 am',
      '-'.repeat(32),
      'Masala tea',
      '  1 x Rs.20                Rs.20',
      '-'.repeat(32),
      'Taxable value           Rs.19.04',
      'CGST @2.5%               Rs.0.48',
      'SGST @2.5%               Rs.0.48',
      'TOTAL      Rs.20',
      'Paid by                      UPI',
      '-'.repeat(32),
      'Thank you',
    ]);
    // Two-column lines fill the paper exactly; big lines are double width, so half.
    for (const t of text.filter((x) => / {2,}\S+$/.test(x) && !x.startsWith('TOTAL'))) expect(t).toHaveLength(32);
    for (const r of rows) expect(r.text.length).toBeLessThanOrEqual(r.big ? 16 : 32);
    expect(rows.find((r) => r.text.startsWith('TOTAL'))).toMatchObject({ big: true, bold: true });
  });

  it('shows options and their price in the line', async () => {
    const b = await bill([{ menuItemId: 'tea', qty: 2, modifierIds: ['large'] }]);
    const text = receiptRows(b, shop, 32).map((r) => r.text);
    expect(text).toContain('Masala tea (Large)');
    expect(text).toContain('  2 x Rs.30                Rs.60');
  });

  it('a composition bill carries the legend and no tax lines', async () => {
    const b = await bill([{ menuItemId: 'tea', qty: 1, modifierIds: [] }], 'composition');
    const text = receiptRows(b, { ...shop, gst_type: 'composition' }, 32).map((r) => r.text);
    expect(text).toContain('BILL OF SUPPLY');
    expect(text.join(' ')).toContain('Composition taxable person, not eligible to collect tax on supplies');
    expect(text.some((t) => t.startsWith('CGST'))).toBe(false);
  });

  it('marks reprints and voided bills', async () => {
    const b = await bill([{ menuItemId: 'tea', qty: 1, modifierIds: [] }]);
    const text = receiptRows(b, shop, 32, { voided: true, reprint: true }).map((r) => r.text);
    expect(text[0]).toBe('*** VOIDED: NOT A VALID BILL ***');
    expect(text).toContain('(Reprint)');
  });
});

describe('80 mm (48 characters)', () => {
  it('uses the full width', async () => {
    const b = await bill([{ menuItemId: 'tea', qty: 1, modifierIds: [] }]);
    const rows = receiptRows(b, shop, 48);
    expect(rows.map((r) => r.text)).toContain('12, Gandhi Road, Tiruchirappalli 620001');
    for (const r of rows) expect(r.text.length).toBeLessThanOrEqual(r.big ? 24 : 48);
  });
});

describe('bytes', () => {
  it('reset, styled lines, feed and cut', () => {
    const bytes = encode([
      { text: 'Hi', align: 'center', big: true, bold: true },
      { text: 'x' },
    ]);
    const arr = [...bytes];
    expect(arr.slice(0, 2)).toEqual(CMD.init);
    expect(arr.slice(2, 11)).toEqual([...CMD.alignCenter, ...CMD.boldOn, ...CMD.sizeBig]);
    expect(arr.slice(11, 14)).toEqual([0x48, 0x69, 0x0a]); // "Hi\n"
    expect(arr.slice(-4)).toEqual(CMD.cut);
    expect(arr.every((b) => b < 256)).toBe(true);
  });

  it('a whole receipt is pure ASCII between commands, and base64 round-trips', async () => {
    const b = await bill([{ menuItemId: 'tea', qty: 1, modifierIds: [] }]);
    const bytes = encode(receiptRows(b, shop, 32));
    expect(bytes.length).toBeGreaterThan(300);
    const back = Uint8Array.from(atob(toBase64(bytes)), (c) => c.charCodeAt(0));
    expect([...back]).toEqual([...bytes]);
  });

  it('the test print fits the chosen width', () => {
    for (const w of [32, 48] as const) {
      for (const r of testRows(w)) expect(r.text.length).toBeLessThanOrEqual(r.big ? w / 2 : w);
    }
  });
});

describe('Phase 6 on the receipt', () => {
  it('a discount gets its own row, each payment part its own line, and the customer is named', async () => {
    const b = await saveBill({
      db,
      deviceId: 'dev',
      deviceCode: 'C1',
      catalogue: { ...testCatalogue, shop },
      cart: [{ menuItemId: 'tea', qty: 3, modifierIds: [] }],
      billDiscountPaise: 1000,
      discountReason: 'Regular',
      paymentMode: 'split',
      paymentParts: [
        { mode: 'cash', paise: 3000 },
        { mode: 'credit', paise: 2000 },
      ],
      customer: { id: 'c1', phone: '9876543210', name: 'Priya' },
      now: new Date('2026-10-04T03:05:00Z'),
    });
    const text = receiptRows(b, shop, 32).map((r) => r.text);
    expect(text).toContain('  3 x Rs.20                Rs.60'); // full price on the line
    expect(text).toContain('Discount (Regular)        -Rs.10');
    expect(text).toContain('Paid by Cash               Rs.30');
    expect(text).toContain('On credit (khata)          Rs.20');
    expect(text).toContain('Customer                   Priya');
    expect(text.join('\n')).not.toContain('9876543210'); // the number is not printed
  });
});

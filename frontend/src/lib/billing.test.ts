import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  businessDate,
  discountAllowed,
  financialYear,
  invoiceNumber,
  percentOff,
  resumeCounters,
  saveBill,
  uuidv7,
} from './billing';
import { PosDB } from './db';
import { testCatalogue } from './test-fixtures';

let db: PosDB;
beforeEach(async () => {
  db = new PosDB(`test-${Math.random()}`);
  await db.open();
});

describe('dates and numbers', () => {
  it('business date follows IST, not UTC', () => {
    expect(businessDate(new Date('2026-10-03T18:40:00Z'))).toBe('2026-10-04'); // 00:10 IST
    expect(businessDate(new Date('2026-10-03T18:20:00Z'))).toBe('2026-10-03'); // 23:50 IST
  });

  it('financial year runs April to March', () => {
    expect(financialYear('2026-10-03')).toBe('26-27');
    expect(financialYear('2027-03-31')).toBe('26-27');
    expect(financialYear('2027-04-01')).toBe('27-28');
    expect(financialYear('2099-12-31')).toBe('99-00');
  });

  it('invoice numbers match the server format', () => {
    expect(invoiceNumber('C1', '26-27', 123)).toBe('C1/26-27/000123');
  });

  it('uuidv7 is valid and sorts by time', () => {
    const a = uuidv7(1_700_000_000_000);
    const b = uuidv7(1_700_000_000_001);
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(a < b).toBe(true);
  });
});

describe('saveBill', () => {
  const save = (now = new Date('2026-10-03T06:00:00Z'), qty = 1) =>
    saveBill({
      db, deviceId: 'dev', deviceCode: 'C1', catalogue: testCatalogue,
      cart: [{ menuItemId: 'tea', qty, modifierIds: [] }], paymentMode: 'cash', now,
    });

  it('numbers bills consecutively and puts them in the outbox', async () => {
    const a = await save();
    const b = await save();
    expect([a.invoiceNo, b.invoiceNo]).toEqual(['C1/26-27/000001', 'C1/26-27/000002']);
    expect(await db.pendingCount()).toBe(2);
    expect(a.payload.totals.total).toBe(2000);
  });

  it('records who rang the bill up, so a later login does not take the credit', async () => {
    const withCashier = await saveBill({
      db, deviceId: 'dev', deviceCode: 'C1', catalogue: testCatalogue,
      cart: [{ menuItemId: 'tea', qty: 1, modifierIds: [] }], paymentMode: 'cash', cashierId: 'ravi',
    });
    expect(withCashier.payload.cashier_id).toBe('ravi');
    expect('cashier_id' in (await save()).payload).toBe(false); // no one known: key left out
  });

  it('restarts numbering in a new financial year', async () => {
    await save(new Date('2027-03-31T12:00:00Z'));
    const april = await save(new Date('2027-04-01T00:00:00Z')); // 05:30 IST on 1 April
    expect(april.invoiceNo).toBe('C1/27-28/000001');
  });

  it('a failed save uses no invoice number (one transaction)', async () => {
    await save();
    await expect(
      saveBill({
        db, deviceId: 'dev', deviceCode: 'C1', catalogue: testCatalogue,
        cart: [{ menuItemId: 'tea', qty: 0, modifierIds: [] }], // invalid: GST code throws
        paymentMode: 'cash', now: new Date('2026-10-03T06:00:00Z'),
      }),
    ).rejects.toThrow();
    expect((await save()).invoiceNo).toBe('C1/26-27/000002');
  });

  it('many saves at once never share a number', async () => {
    const bills = await Promise.all(Array.from({ length: 25 }, () => save()));
    const numbers = new Set(bills.map((b) => b.seq));
    expect(numbers.size).toBe(25);
    expect(Math.max(...numbers)).toBe(25);
  });

  it('resumeCounters never moves the counter backwards', async () => {
    await save();
    await save();
    await save();
    await resumeCounters(db, 'dev', { '26-27': 1 }); // server behind: ignore
    expect((await save()).seq).toBe(4);
    await resumeCounters(db, 'dev', { '26-27': 40 }); // server ahead (wiped tablet): jump
    expect((await save()).seq).toBe(41);
  });
});

describe('Phase 6: discounts, split payment, credit', () => {
  const now = new Date('2026-10-03T06:00:00Z');
  const base = { db: undefined as unknown as PosDB, deviceId: 'dev', deviceCode: 'C1', catalogue: testCatalogue, now };

  it('an undiscounted cash bill sends exactly what it sent before Phase 6', async () => {
    const b = await saveBill({ ...base, db, cart: [{ menuItemId: 'tea', qty: 1, modifierIds: [] }], paymentMode: 'cash' });
    const keys = Object.keys(b.payload).sort();
    expect(keys).toEqual(['gst_type', 'id', 'invoice_no', 'lines', 'local_seq', 'payment_mode', 'sold_at', 'totals']);
    expect(Object.keys(b.payload.lines[0].totals).sort()).toEqual(['cgst', 'gross', 'sgst', 'taxable', 'total']);
    expect(Object.keys(b.payload.totals)).not.toContain('discount');
  });

  it('line and bill discounts are priced with the shared GST rule and sent with the reason', async () => {
    const b = await saveBill({
      ...base,
      db,
      cart: [{ menuItemId: 'tea', qty: 2, modifierIds: [], discountPaise: 400 }],
      billDiscountPaise: 100,
      discountReason: 'Regular customer',
      paymentMode: 'cash',
    });
    expect(b.payload.lines[0].discount_paise).toBe(400);
    expect(b.payload.lines[0].totals.discount).toBe(500);
    expect(b.payload.bill_discount_paise).toBe(100);
    expect(b.payload.discount_reason).toBe('Regular customer');
    expect(b.payload.totals).toMatchObject({ discount: 500, total: 3500 });
    expect(b.totalPaise).toBe(3500);
  });

  it('split payment parts must add up to the bill', async () => {
    const cart = [{ menuItemId: 'tea', qty: 3, modifierIds: [] }];
    const ok = await saveBill({ ...base, db, cart, paymentMode: 'split', paymentParts: [{ mode: 'cash', paise: 2000 }, { mode: 'upi', paise: 4000 }] });
    expect(ok.payload.payment_parts).toEqual([{ mode: 'cash', paise: 2000 }, { mode: 'upi', paise: 4000 }]);
    await expect(
      saveBill({ ...base, db, cart, paymentMode: 'split', paymentParts: [{ mode: 'cash', paise: 100 }] }),
    ).rejects.toThrow(/add up/);
  });

  it('credit needs a customer, who travels with the bill', async () => {
    const cart = [{ menuItemId: 'tea', qty: 1, modifierIds: [] }];
    await expect(saveBill({ ...base, db, cart, paymentMode: 'credit' })).rejects.toThrow(/customer/);
    const c = { id: 'c1', phone: '9876543210', name: 'Priya' };
    const b = await saveBill({ ...base, db, cart, paymentMode: 'credit', customer: c });
    expect(b.payload.customer).toEqual(c);
  });

  it('cashier discount limits, and rupees from a percentage', () => {
    expect(discountAllowed({ discountPaise: 1000, grossPaise: 10000, maxBp: 1000, isOwner: false })).toBe(true);
    expect(discountAllowed({ discountPaise: 1001, grossPaise: 10000, maxBp: 1000, isOwner: false })).toBe(false);
    expect(discountAllowed({ discountPaise: 9000, grossPaise: 10000, maxBp: 1000, isOwner: true })).toBe(true);
    expect(percentOff(12.5, 4000)).toBe(500);
    expect(percentOff(10, 2050)).toBe(205); // half up, like the GST rounding
    expect(percentOff(33.33, 100)).toBe(33);
  });
});

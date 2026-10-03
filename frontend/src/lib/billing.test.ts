import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  businessDate,
  financialYear,
  invoiceNumber,
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

import 'fake-indexeddb/auto';
import { describe, expect, it } from 'vitest';
import type { Api } from './api';
import { HttpError, NetworkError } from './api';
import { saveBill } from './billing';
import { testCatalogue } from './test-fixtures';
import { PosDB } from './db';
import { SyncWorker, syncOnce } from './sync';
import type { SyncBill, SyncResult } from './types';

const sale = (db: PosDB) =>
  saveBill({
    db, deviceId: 'dev', deviceCode: 'C1', catalogue: testCatalogue,
    cart: [{ menuItemId: 'tea', qty: 1, modifierIds: [] }], paymentMode: 'cash',
  });

/** A fake server: accepts everything, remembers what it was sent. */
function fakeApi(opts: { delayMs?: number; reject?: Set<string> } = {}) {
  const received: string[][] = [];
  const api = {
    async post(_path: string, body: { bills: SyncBill[] }) {
      received.push(body.bills.map((b) => b.id));
      await new Promise((r) => setTimeout(r, opts.delayMs ?? 0));
      const results: SyncResult[] = body.bills.map((b) => ({
        id: b.id,
        status: opts.reject?.has(b.id) ? 'rejected' : 'accepted',
        invoice_no: b.invoice_no,
        totals_mismatch: false,
        reason: opts.reject?.has(b.id) ? 'device_clock_ahead' : null,
      }));
      return { results };
    },
  };
  return { api: api as unknown as Api, received };
}

describe('syncOnce', () => {
  it('sends oldest first, in batches, and empties the outbox', async () => {
    const db = new PosDB(`s-${Math.random()}`);
    const bills = [];
    for (let i = 0; i < 7; i++) bills.push(await sale(db));
    const { api, received } = fakeApi();
    const summary = await syncOnce(api, db, 'dev', 3);
    expect(received.map((b) => b.length)).toEqual([3, 3, 1]);
    expect(received.flat()).toEqual(bills.map((b) => b.id));
    expect(summary).toEqual({ sent: 7, synced: 7, rejected: 0 });
    expect(await db.pendingCount()).toBe(0);
  });

  it('keeps rejected bills, with the reason, out of the outbox', async () => {
    const db = new PosDB(`s-${Math.random()}`);
    const bad = await sale(db);
    await sale(db);
    const { api } = fakeApi({ reject: new Set([bad.id]) });
    await syncOnce(api, db, 'dev');
    const stored = await db.bills.get(bad.id);
    expect(stored?.status).toBe('rejected');
    expect(stored?.reason).toBe('device_clock_ahead');
    expect(await db.pendingCount()).toBe(0);
  });

  it('leaves the outbox untouched when the network fails', async () => {
    const db = new PosDB(`s-${Math.random()}`);
    await sale(db);
    const api = { post: () => Promise.reject(new NetworkError('offline')) } as unknown as Api;
    await expect(syncOnce(api, db, 'dev')).rejects.toBeInstanceOf(NetworkError);
    expect(await db.pendingCount()).toBe(1);
  });
});

describe('SyncWorker.kick', () => {
  it('a sale saved DURING a sync is sent straight after, not 30 s later', async () => {
    const db = new PosDB(`s-${Math.random()}`);
    const first = await sale(db);
    const { api, received } = fakeApi({ delayMs: 50 });
    const worker = new SyncWorker(api, db, 'dev');

    const running = worker.kick(); // sync of the first bill is in flight...
    await new Promise((r) => setTimeout(r, 10));
    const second = await sale(db); // ...a new sale is saved...
    await worker.kick(); // ...and its "send now" must not be dropped
    await running;

    expect(received).toEqual([[first.id], [second.id]]);
    expect(await db.pendingCount()).toBe(0);
    worker.stop();
  });

  it('the badge counts a new sale at once, not when the sync running now ends', async () => {
    const db = new PosDB(`s-${Math.random()}`);
    await sale(db);
    const { api } = fakeApi({ delayMs: 50 });
    const worker = new SyncWorker(api, db, 'dev');
    const seen: number[] = [];
    worker.subscribe((s) => seen.push(s.pending));

    const running = worker.kick();
    await new Promise((r) => setTimeout(r, 10));
    await sale(db); // saved while the first bill is still being sent
    await worker.kick();
    // Before the in-flight run finishes, the badge must not say "All bills sent".
    expect(seen.at(-1)).toBeGreaterThan(0);
    await running;
    expect(seen.at(-1)).toBe(0);
    worker.stop();
  });
});

describe('SyncWorker: one stuck kind of record never holds back the bills', () => {
  it('bills are still sent when the order events are refused', async () => {
    const db = new PosDB(`s-${Math.random()}`);
    const { openOrder } = await import('./orders');
    await openOrder(db, { orderType: 'takeaway' }, 'u1');
    const bill = await sale(db);
    const sent: string[] = [];
    const api = {
      async post(path: string, body: { bills?: SyncBill[] }) {
        sent.push(path);
        if (path === '/sync/orders') throw new HttpError(422, 'Unprocessable');
        return {
          results: (body.bills ?? []).map((b) => ({
            id: b.id, status: 'accepted', invoice_no: b.invoice_no, totals_mismatch: false, reason: null,
          })),
        };
      },
      async get() {
        return { server_time: new Date().toISOString(), orders: [] };
      },
    } as unknown as Api;
    const worker = new SyncWorker(api, db, 'dev');
    let lastError: string | null = null;
    worker.subscribe((st) => (lastError = st.lastError));
    await worker.kick();
    worker.stop();
    expect(sent).toContain('/sync/bills');
    expect((await db.bills.get(bill.id))?.status).toBe('synced');
    // The failure is still shown: the order events are waiting.
    expect(lastError).toBeTruthy();
  });
});

describe('SyncWorker.refreshCounts', () => {
  it('an older count that answers late never overwrites a newer one', async () => {
    // The flaky sales spec: the end of one sync read the outbox (0 waiting) just
    // before a new bill was saved, but answered after the new bill's own count
    // (1 waiting), so the badge said "All bills sent" with a bill still to send.
    const db = new PosDB(`s-${Math.random()}`);
    const worker = new SyncWorker(fakeApi().api, db, 'dev');
    let last = -1;
    worker.subscribe((s) => (last = s.pending));
    const real = db.pendingCount.bind(db);
    let slowOnce = true;
    db.pendingCount = async () => {
      const n = await real();
      if (slowOnce) {
        slowOnce = false;
        await new Promise((r) => setTimeout(r, 30));
      }
      return n;
    };
    const older = worker.refreshCounts(); // reads 0, answers late
    await new Promise((r) => setTimeout(r, 5));
    await sale(db);
    await worker.refreshCounts(); // reads 1
    await older;
    expect(last).toBe(1);
    worker.stop();
  });
});

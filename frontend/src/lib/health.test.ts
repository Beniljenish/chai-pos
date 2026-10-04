import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Api } from './api';
import { saveBill } from './billing';
import { PosDB } from './db';
import { HealthReporter, buildReport, dayTime } from './health';
import { testCatalogue } from './test-fixtures';

let db: PosDB;
beforeEach(() => {
  db = new PosDB(`health-${Math.random()}`);
});

const sell = (now: string) =>
  saveBill({
    db,
    deviceId: 'dev',
    deviceCode: 'C1',
    catalogue: testCatalogue,
    cart: [{ menuItemId: 'tea', qty: 1, modifierIds: [] }],
    paymentMode: 'cash',
    now: new Date(now),
  });

describe('what the tablet holds', () => {
  it('reports the last printed number and every bill it still holds', async () => {
    const a = await sell('2026-10-03T05:00:00Z');
    const b = await sell('2026-10-03T06:00:00Z');
    const c = await sell('2026-10-03T07:00:00Z');
    await db.bills.update(a.id, { status: 'synced' });
    await db.bills.update(c.id, { status: 'rejected', reason: 'bill_too_old' });
    await db.counters.put({ key: 'other-device:26-27', lastSeq: 99 }); // not ours
    // The kitchen ticket count shares the store; it is not an invoice series
    // (sending it made the server refuse every report from this tablet).
    await db.counters.put({ key: 'dev:kot:2026-10-03', lastSeq: 7 });

    const r = await buildReport(db, 'dev', true, 'abc1234');
    expect(r.seq_by_fy).toEqual({ '26-27': 3 });
    expect(r.held_seqs_by_fy).toEqual({ '26-27': [2, 3] }); // waiting + refused: not lost
    expect(r.pending_bills).toBe(1);
    expect(r.rejected).toBe(1);
    expect(r.oldest_pending_at).toBe(b.soldAt);
    expect([r.persisted_storage, r.app_version]).toEqual([true, 'abc1234']);
    expect(r.pending_ops).toBe(0);
  });

  it('counts drawer operations still waiting to send', async () => {
    const { startShift } = await import('./shift');
    await startShift(db, 50000, { id: 'ravi', name: 'Ravi' });
    expect((await buildReport(db, 'dev', null, null)).pending_ops).toBe(1);
  });

  it('an empty tablet reports nothing held', async () => {
    const r = await buildReport(db, 'dev', null, null);
    expect(r).toMatchObject({ seq_by_fy: {}, pending_bills: 0, oldest_pending_at: null, held_seqs_by_fy: {} });
  });
});

describe('sending it', () => {
  it('sends on change or every 5 minutes, and never throws', async () => {
    const post = vi.fn().mockResolvedValue(undefined);
    const api = { post } as unknown as Api;
    const rep = new HealthReporter(api, db, 'dev');
    expect(await rep.maybeSend(0)).toBe(true);
    expect(await rep.maybeSend(60_000)).toBe(false); // nothing changed, 1 minute later
    await sell('2026-10-03T05:00:00Z');
    expect(await rep.maybeSend(120_000)).toBe(true); // a new bill: changed
    expect(await rep.maybeSend(120_000 + 5 * 60_000)).toBe(true); // 5 minutes: refresh "last seen"
    expect(post).toHaveBeenLastCalledWith('/devices/dev/report', expect.objectContaining({ pending_bills: 1 }));

    post.mockRejectedValueOnce(new Error('offline'));
    await sell('2026-10-03T06:00:00Z');
    expect(await rep.maybeSend(10 * 60_000)).toBe(false); // failed: tries again next time
    expect(await rep.maybeSend(10 * 60_000 + 1)).toBe(true);
  });
});

it('says how long ago in plain words', async () => {
  const { ago } = await import('./health');
  const now = Date.parse('2026-10-04T12:00:00Z');
  expect(ago('2026-10-04T11:59:40Z', now)).toBe('just now');
  expect(ago('2026-10-04T11:55:00Z', now)).toBe('5 min ago');
  expect(ago('2026-10-04T09:00:00Z', now)).toBe('3 h ago');
  expect(ago('2026-10-03T12:00:00Z', now)).toBe('1 day ago');
  expect(ago('2026-10-01T12:00:00Z', now)).toBe('3 days ago');
});

describe('dayTime', () => {
  it('formats a day and time in IST (the Tablets screen crashed on this)', () => {
    // Intl refuses timeStyle together with day/month: a RangeError at render,
    // exactly when a tablet had bills waiting, the case the screen is for.
    expect(dayTime('2026-10-04T06:30:00Z')).toMatch(/^4 Oct,? 12:00\s?pm$/i);
  });
});

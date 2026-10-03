import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import { PosDB } from './db';
import {
  adoptServerState,
  currentShift,
  drawerTotalPaise,
  endShift,
  lastCount,
  recordCash,
  rupeesToPaise,
  startShift,
} from './shift';

let db: PosDB;
const ravi = { id: 'ravi', name: 'Ravi' };
beforeEach(() => {
  db = new PosDB(`shift-${Math.random()}`);
});

const ops = async () => (await db.shiftOps.orderBy('seq').toArray()).map((o) => o.payload);

describe('a shift on the tablet', () => {
  it('opens, records cash, and closes, queuing each step in order', async () => {
    const s = await startShift(db, 50000, ravi, new Date('2026-10-04T01:30:00Z'));
    await recordCash(db, 'pay_out', 30000, ' Milkman ', ravi);
    await endShift(db, 31800, 'ok', ravi, new Date('2026-10-04T09:00:00Z'));

    const sent = await ops();
    expect(sent.map((o) => o.op)).toEqual(['open', 'cash', 'close']);
    expect(sent[0]).toMatchObject({ id: s.id, opening_float_paise: 50000, cashier_id: 'ravi' });
    expect(sent[1]).toMatchObject({ shift_id: s.id, kind: 'pay_out', amount_paise: 30000, reason: 'Milkman' });
    expect(sent[2]).toMatchObject({ shift_id: s.id, counted_cash_paise: 31800 });
    expect(await currentShift(db)).toBeUndefined();
    expect(await lastCount(db)).toMatchObject({ countedPaise: 31800, byName: 'Ravi' });
    expect(await db.pendingCount()).toBe(3); // shown in the "waiting" badge with bills
  });

  it('refuses a second shift, and cash or a close with no shift', async () => {
    await startShift(db, 0, ravi);
    await expect(startShift(db, 0, ravi)).rejects.toThrow('already open');
    await endShift(db, 0, '', ravi);
    await expect(recordCash(db, 'pay_in', 100, 'x', ravi)).rejects.toThrow('No shift');
    await expect(endShift(db, 0, '', ravi)).rejects.toThrow('No shift');
    await expect(startShift(db, -1, ravi)).rejects.toThrow();
  });
});

describe('server state after a restart', () => {
  const server = {
    open_shift: {
      id: 'srv',
      opened_by: 'arun',
      opened_by_name: 'Arun',
      opened_at: '2026-10-04T01:00:00Z',
      opening_float_paise: 40000,
    },
    last_counted: { counted_cash_paise: 12300, by_name: 'Arun', at: '2026-10-03T15:00:00Z' },
  };

  it('a wiped tablet picks up the shift still open on the server', async () => {
    await adoptServerState(db, server);
    expect(await currentShift(db)).toMatchObject({ id: 'srv', openedByName: 'Arun', openingFloatPaise: 40000 });
    expect(await lastCount(db)).toMatchObject({ countedPaise: 12300 });
  });

  it('never re-opens a shift this tablet has ended but not yet sent', async () => {
    await startShift(db, 0, ravi);
    await endShift(db, 0, '', ravi);
    await adoptServerState(db, server);
    expect(await currentShift(db)).toBeUndefined();
  });

  it("the tablet's own open shift wins", async () => {
    const mine = await startShift(db, 100, ravi);
    await adoptServerState(db, server);
    expect((await currentShift(db))?.id).toBe(mine.id);
  });
});

describe('counting the drawer', () => {
  it('adds notes and coins', () => {
    expect(drawerTotalPaise({ 500: '2', 100: '3', 10: '4' }, '17.5')).toBe(135750); // 1000 + 300 + 40 + 17.50
    expect(drawerTotalPaise({}, '')).toBe(0);
    expect(drawerTotalPaise({ 500: '-1', 200: 'x' }, '-3')).toBe(0);
  });
  it('reads rupee amounts strictly', () => {
    expect(rupeesToPaise('500')).toBe(50000);
    expect(rupeesToPaise('20.5')).toBe(2050);
    expect(rupeesToPaise('1.234')).toBeNaN();
    expect(rupeesToPaise('')).toBeNaN();
  });
});

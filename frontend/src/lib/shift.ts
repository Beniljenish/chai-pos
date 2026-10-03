/**
 * The cash drawer on this tablet (README, "Shifts and cash"). Tested in shift.test.ts.
 *
 * A shift starts with the first bill (or by hand) and ends when someone counts
 * the drawer. Everything happens on the tablet first, offline if need be, and is
 * sent to the server through its own outbox, before the bills that refer to it.
 */
import { uuidv7 } from './billing';
import type { Api } from './api';
import type { PosDB } from './db';

export interface LocalShift {
  id: string;
  openedAt: string;
  openingFloatPaise: number;
  openedById: string;
  openedByName: string;
}

export interface LastCount {
  countedPaise: number;
  byName: string;
  at: string;
}

export interface Person {
  id: string;
  name: string;
}

export const currentShift = (db: PosDB) => db.getMeta<LocalShift>('shift');
export const lastCount = (db: PosDB) => db.getMeta<LastCount>('lastCounted');

async function queue(db: PosDB, payload: Record<string, unknown>) {
  const last = await db.shiftOps.orderBy('seq').last();
  await db.shiftOps.add({ id: payload.id as string, seq: (last?.seq ?? 0) + 1, status: 'pending', payload });
}

export async function startShift(db: PosDB, floatPaise: number, who: Person, now = new Date()): Promise<LocalShift> {
  if (!Number.isInteger(floatPaise) || floatPaise < 0) throw new Error('Enter the cash in the drawer');
  return db.transaction('rw', db.meta, db.shiftOps, async () => {
    if (await currentShift(db)) throw new Error('A shift is already open on this tablet');
    const shift: LocalShift = {
      id: uuidv7(now.getTime()),
      openedAt: now.toISOString(),
      openingFloatPaise: floatPaise,
      openedById: who.id,
      openedByName: who.name,
    };
    await db.setMeta('shift', shift);
    await queue(db, {
      op: 'open',
      id: shift.id,
      at: shift.openedAt,
      opening_float_paise: floatPaise,
      cashier_id: who.id,
    });
    return shift;
  });
}

export async function recordCash(
  db: PosDB,
  kind: 'pay_out' | 'pay_in',
  amountPaise: number,
  reason: string,
  who: Person,
  now = new Date(),
): Promise<void> {
  if (!Number.isInteger(amountPaise) || amountPaise <= 0) throw new Error('Enter the amount');
  if (!reason.trim()) throw new Error('Say what it was for');
  await db.transaction('rw', db.meta, db.shiftOps, async () => {
    const shift = await currentShift(db);
    if (!shift) throw new Error('No shift is open');
    await queue(db, {
      op: 'cash',
      id: uuidv7(now.getTime()),
      shift_id: shift.id,
      at: now.toISOString(),
      kind,
      amount_paise: amountPaise,
      reason: reason.trim(),
      cashier_id: who.id,
    });
  });
}

/** Blind: the person counting is never shown what the drawer should hold. */
export async function endShift(db: PosDB, countedPaise: number, note: string, who: Person, now = new Date()) {
  if (!Number.isInteger(countedPaise) || countedPaise < 0) throw new Error('Enter the cash you counted');
  await db.transaction('rw', db.meta, db.shiftOps, async () => {
    const shift = await currentShift(db);
    if (!shift) throw new Error('No shift is open');
    await queue(db, {
      op: 'close',
      id: uuidv7(now.getTime()),
      shift_id: shift.id,
      at: now.toISOString(),
      counted_cash_paise: countedPaise,
      note: note.trim(),
      cashier_id: who.id,
    });
    await db.setMeta('shift', null);
    await db.setMeta('lastCounted', { countedPaise, byName: who.name, at: now.toISOString() } satisfies LastCount);
  });
}

/** Send pending drawer operations, oldest first. Same contract as bills. */
export async function syncShiftOps(api: Api, db: PosDB, deviceId: string): Promise<number> {
  const batch = await db.shiftOps
    .where('[status+seq]')
    .between(['pending', -Infinity], ['pending', Infinity])
    .limit(100)
    .toArray();
  if (batch.length === 0) return 0;
  const { results } = await api.post<{ results: { id: string; status: string; reason: string | null }[] }>(
    '/sync/shifts',
    { device_id: deviceId, ops: batch.map((o) => o.payload) },
  );
  await db.transaction('rw', db.shiftOps, async () => {
    for (const r of results) {
      if (r.status === 'accepted' || r.status === 'duplicate') await db.shiftOps.update(r.id, { status: 'synced' });
      else await db.shiftOps.update(r.id, { status: 'rejected', reason: r.reason ?? 'rejected' });
    }
  });
  return batch.length;
}

export interface ServerShiftState {
  open_shift: {
    id: string;
    opened_by: string;
    opened_by_name: string;
    opened_at: string;
    opening_float_paise: number;
  } | null;
  last_counted: { counted_cash_paise: number; by_name: string; at: string } | null;
}

/**
 * After a login or a restart, online: fill in what this tablet does not know.
 * The tablet's own record wins (it may hold operations not yet sent); the
 * server's fills the gaps, e.g. after the browser's storage was cleared, so a
 * second shift is not started over one that is still open.
 */
export async function adoptServerState(db: PosDB, s: ServerShiftState): Promise<void> {
  await db.transaction('rw', db.meta, db.shiftOps, async () => {
    const local = await currentShift(db);
    const unsentClose = await db.shiftOps
      .where('status')
      .equals('pending')
      .filter((o) => o.payload.op === 'close')
      .count();
    if (!local && s.open_shift && unsentClose === 0) {
      await db.setMeta('shift', {
        id: s.open_shift.id,
        openedAt: s.open_shift.opened_at,
        openingFloatPaise: s.open_shift.opening_float_paise,
        openedById: s.open_shift.opened_by,
        openedByName: s.open_shift.opened_by_name,
      } satisfies LocalShift);
    }
    if (!(await lastCount(db)) && s.last_counted) {
      await db.setMeta('lastCounted', {
        countedPaise: s.last_counted.counted_cash_paise,
        byName: s.last_counted.by_name,
        at: s.last_counted.at,
      } satisfies LastCount);
    }
  });
}

// ---------------------------------------------------------------- counting
/** Notes counted one by one; coins as one rupee amount (nobody counts coins by type). */
export const NOTES = [500, 200, 100, 50, 20, 10] as const;

export function drawerTotalPaise(notes: Partial<Record<number, string>>, coinsRupees: string): number {
  let rupees = 0;
  for (const n of NOTES) {
    const c = Number(notes[n] || 0);
    if (Number.isFinite(c) && c > 0) rupees += Math.floor(c) * n;
  }
  const coins = Number(coinsRupees || 0);
  return Math.round((rupees + (Number.isFinite(coins) && coins > 0 ? coins : 0)) * 100);
}

/** "₹500" typed as "500" or "500.50" into paise; NaN for anything else. */
export function rupeesToPaise(text: string): number {
  if (!/^\d+(\.\d{1,2})?$/.test(text.trim())) return NaN;
  return Math.round(Number(text) * 100);
}

/** Shifts are on unless the owner switched them off (a catalogue cached before
 * shifts existed has no flag: on). */
export const shiftsOn = (cashShifts: boolean | undefined): boolean => cashShifts !== false;

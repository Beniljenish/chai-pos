/**
 * What this tablet holds, for the owner's Tablets screen (README, "Bill safety").
 * Tested in health.test.ts.
 *
 * The server cannot see a bill it never received. Only the tablet knows the
 * last invoice number it printed and which bills it still holds, so it says so
 * whenever it syncs; a printed number the server lacks and the tablet no longer
 * holds is a lost bill.
 */
import type { Api } from './api';
import type { PosDB } from './db';

export interface DeviceReport {
  seq_by_fy: Record<string, number>;
  pending_bills: number;
  pending_ops: number;
  rejected: number;
  oldest_pending_at: string | null;
  held_seqs_by_fy: Record<string, number[]>;
  persisted_storage: boolean | null;
  app_version: string | null;
}

export async function buildReport(
  db: PosDB,
  deviceId: string,
  persisted: boolean | null,
  appVersion: string | null,
): Promise<DeviceReport> {
  const prefix = `${deviceId}:`;
  const seq_by_fy: Record<string, number> = {};
  for (const c of await db.counters.toArray()) {
    if (c.key.startsWith(prefix)) seq_by_fy[c.key.slice(prefix.length)] = c.lastSeq;
  }
  const held = await db.bills.where('status').anyOf('pending', 'rejected').toArray();
  const held_seqs_by_fy: Record<string, number[]> = {};
  for (const b of held) (held_seqs_by_fy[b.fy] ??= []).push(b.seq);
  for (const fy of Object.keys(held_seqs_by_fy)) held_seqs_by_fy[fy].sort((a, b) => a - b);
  const pending = held.filter((b) => b.status === 'pending');
  const oldest = pending.map((b) => b.soldAt).sort()[0] ?? null;
  const [pending_ops, rejected_ops] = await Promise.all([
    Promise.all([
      db.shiftOps.where('status').equals('pending').count(),
      db.orderEvents.where('status').equals('pending').count(),
    ]).then(([a, b]) => a + b),
    Promise.all([
      db.shiftOps.where('status').equals('rejected').count(),
      db.orderEvents.where('status').equals('rejected').count(),
    ]).then(([a, b]) => a + b),
  ]);
  return {
    seq_by_fy,
    pending_bills: pending.length,
    pending_ops,
    rejected: held.length - pending.length + rejected_ops,
    oldest_pending_at: oldest,
    held_seqs_by_fy,
    persisted_storage: persisted,
    app_version: appVersion,
  };
}

/**
 * Send the report when it changed, or at least every 5 minutes (so "last seen"
 * stays fresh). Never throws: health reporting must not disturb billing.
 */
export class HealthReporter {
  private lastBody = '';
  private lastAt = 0;
  private api: Api;
  private db: PosDB;
  private deviceId: string;
  private everyMs: number;

  constructor(api: Api, db: PosDB, deviceId: string, everyMs = 5 * 60_000) {
    this.api = api;
    this.db = db;
    this.deviceId = deviceId;
    this.everyMs = everyMs;
  }

  async maybeSend(now = Date.now()): Promise<boolean> {
    try {
      const persisted =
        typeof navigator !== 'undefined' && navigator.storage?.persisted ? await navigator.storage.persisted() : null;
      const version = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : null;
      const report = await buildReport(this.db, this.deviceId, persisted, version);
      const body = JSON.stringify(report);
      if (body === this.lastBody && now - this.lastAt < this.everyMs) return false;
      await this.api.post(`/devices/${this.deviceId}/report`, report);
      this.lastBody = body;
      this.lastAt = now;
      return true;
    } catch {
      return false; // offline or logged out: try again next sync
    }
  }
}

/** "just now", "5 min ago", "3 h ago", "2 days ago". */
export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? '' : 's'} ago`;
}

/** "4 Oct, 12:00 pm" in IST: when a tablet's oldest waiting bill was made. */
export const dayTime = (iso: string) =>
  // Not timeStyle: Intl throws when it is combined with day/month.
  new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso));

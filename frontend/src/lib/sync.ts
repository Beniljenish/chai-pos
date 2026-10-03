/**
 * Sending the outbox to the server.
 *
 * syncOnce(): sends pending bills oldest-first in batches of 50. Per bill, the
 * server says accepted / duplicate (both mean "safely stored": mark synced) or
 * rejected (keep it, show the reason). Safe to run again at any time: the server
 * de-duplicates by bill id, so a retry after a lost response is harmless.
 *
 * SyncWorker: runs syncOnce after each sale, when the network comes back, when
 * the app comes to the front, and every 30 s; backs off after failures; uses a
 * Web Lock so two open tabs never sync at once.
 */
import { AuthRequiredError, HttpError, NetworkError, type Api } from './api';
import type { PosDB } from './db';
import { pullLive, syncOrderEvents } from './orders';
import { syncShiftOps } from './shift';
import { HealthReporter } from './health';
import type { SyncResult } from './types';

export const BATCH_SIZE = 50;

export interface SyncSummary {
  sent: number;
  synced: number;
  rejected: number;
}

export async function syncOnce(
  api: Api,
  db: PosDB,
  deviceId: string,
  batchSize = BATCH_SIZE,
): Promise<SyncSummary> {
  const summary: SyncSummary = { sent: 0, synced: 0, rejected: 0 };
  for (;;) {
    const batch = await db.bills
      .where('[status+seq]')
      .between(['pending', -Infinity], ['pending', Infinity])
      .limit(batchSize)
      .toArray();
    if (batch.length === 0) return summary;

    const { results } = await api.post<{ results: SyncResult[] }>('/sync/bills', {
      device_id: deviceId,
      bills: batch.map((b) => b.payload),
    });
    summary.sent += batch.length;

    await db.transaction('rw', db.bills, async () => {
      for (const r of results) {
        if (r.status === 'accepted' || r.status === 'duplicate') {
          await db.bills.update(r.id, {
            status: 'synced',
            totalsMismatch: r.totals_mismatch,
            reason: undefined,
          });
          summary.synced++;
        } else {
          await db.bills.update(r.id, { status: 'rejected', reason: r.reason ?? 'rejected' });
          summary.rejected++;
        }
      }
    });
    if (batch.length < batchSize) return summary;
  }
}

export type SyncState = {
  pending: number;
  rejected: number;
  syncing: boolean;
  lastError: string | null;
  needsLogin: boolean;
  lastSyncedAt: string | null;
};

type Listener = (s: SyncState) => void;

export class SyncWorker {
  private state: SyncState = {
    pending: 0,
    rejected: 0,
    syncing: false,
    lastError: null,
    needsLogin: false,
    lastSyncedAt: null,
  };
  private listeners = new Set<Listener>();
  private failures = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = true;
  private cleanup: (() => void)[] = [];
  private api: Api;
  private db: PosDB;
  private deviceId: string;
  private intervalMs: number;
  private health: HealthReporter;

  constructor(api: Api, db: PosDB, deviceId: string, intervalMs = 30_000) {
    this.api = api;
    this.db = db;
    this.deviceId = deviceId;
    this.intervalMs = intervalMs;
    this.health = new HealthReporter(api, db, deviceId);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => this.listeners.delete(fn);
  }

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    const kick = () => void this.kick();
    const onVisible = () => document.visibilityState === 'visible' && kick();
    window.addEventListener('online', kick);
    document.addEventListener('visibilitychange', onVisible);
    this.cleanup.push(
      () => window.removeEventListener('online', kick),
      () => document.removeEventListener('visibilitychange', onVisible),
    );
    void this.kick();
  }

  stop() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.cleanup.forEach((f) => f());
    this.cleanup = [];
  }

  private running = false;
  private again = false;

  /**
   * Try to sync now (e.g. straight after a sale). If a sync is already running,
   * remember the request and run once more when it finishes, so a bill saved
   * mid-sync is sent straight away rather than waiting for the next timer.
   */
  async kick(): Promise<void> {
    if (this.running) {
      this.again = true;
      // A bill saved mid-sync: show it as waiting now, not when this run ends
      // (until then the badge would still say "All bills sent").
      await this.refreshCounts();
      return;
    }
    this.running = true;
    if (this.timer) clearTimeout(this.timer);
    try {
      do {
        this.again = false;
        await this.withCrossTabLock(() => this.runOnce());
      } while (this.again);
    } finally {
      this.running = false;
      this.schedule();
    }
  }

  /** Only one open tab syncs at a time (the server would cope, but it is wasteful). */
  private async withCrossTabLock(fn: () => Promise<void>) {
    if (typeof navigator !== 'undefined' && navigator.locks) {
      await navigator.locks.request('chai-pos-sync', fn);
    } else {
      await fn();
    }
  }

  private async runOnce() {
    await this.refreshCounts(); // what is waiting right now, shown while it is sent
    this.set({ syncing: true });
    try {
      // Drawer operations first: a bill names its shift, which must already be there.
      await syncShiftOps(this.api, this.db, this.deviceId);
      // Then orders: a settled bill names its order, which must already be there.
      await syncOrderEvents(this.api, this.db, this.deviceId);
      await syncOnce(this.api, this.db, this.deviceId);
      await pullLive(this.api, this.db); // what the other devices did
      this.failures = 0;
      this.set({ lastError: null, needsLogin: false, lastSyncedAt: new Date().toISOString() });
    } catch (e) {
      this.failures++;
      if (e instanceof AuthRequiredError) {
        this.set({ needsLogin: true, lastError: 'Log in again to send bills' });
      } else if (e instanceof HttpError && e.status === 403) {
        this.set({ lastError: 'This tablet has been switched off by the owner' });
      } else if (e instanceof NetworkError) {
        this.set({ lastError: 'Offline: bills are saved and will be sent later' });
      } else {
        this.set({ lastError: e instanceof Error ? e.message : 'Sync failed' });
      }
    } finally {
      await this.refreshCounts();
      this.set({ syncing: false });
    }
    // After the bills, even if they failed (a stuck tablet is exactly what the
    // owner needs to hear about): tell the owner what this tablet holds. Offline
    // or logged out it simply fails, quietly. Never throws.
    if (!this.state.needsLogin) await this.health.maybeSend();
  }

  private schedule() {
    if (this.stopped) return;
    // After failures: 2 s, 4 s, 8 s ... capped at the normal interval.
    const delay = this.failures ? Math.min(2000 * 2 ** (this.failures - 1), this.intervalMs) : this.intervalMs;
    this.timer = setTimeout(() => void this.kick(), delay);
  }

  private countSeq = 0;

  async refreshCounts() {
    // Reads can answer out of order (a sync ending while a sale is saved): only
    // the most recently started read may set the badge.
    const seq = ++this.countSeq;
    const [pending, rejected] = await Promise.all([
      this.db.pendingCount(),
      Promise.all([
        this.db.bills.where('status').equals('rejected').count(),
        this.db.shiftOps.where('status').equals('rejected').count(),
        this.db.orderEvents.where('status').equals('rejected').count(),
      ]).then(([a, b, c]) => a + b + c),
    ]);
    if (seq === this.countSeq) this.set({ pending, rejected });
  }

  private set(patch: Partial<SyncState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l(this.state));
  }
}

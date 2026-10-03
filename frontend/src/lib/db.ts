/**
 * Everything the tablet keeps locally, in IndexedDB (via Dexie).
 *
 * - meta:      small key/value settings (refresh token, device, logged-in user)
 * - catalogue: the last menu downloaded from the server, with its ETag
 * - counters:  the invoice sequence per device per financial year
 * - bills:     every bill made on this tablet. status "pending" = the outbox.
 */
import Dexie, { type EntityTable } from 'dexie';
import type { Catalogue, SyncBill } from './types';

export type BillStatus = 'pending' | 'synced' | 'rejected';

export interface LocalBill {
  id: string;
  seq: number;
  fy: string;
  invoiceNo: string;
  soldAt: string; // ISO
  businessDate: string; // YYYY-MM-DD, IST
  totalPaise: number;
  status: BillStatus;
  reason?: string; // when rejected
  totalsMismatch?: boolean;
  payload: SyncBill; // exactly what is sent to /sync/bills
}

export interface MetaRow {
  key: string;
  value: unknown;
}

export interface CounterRow {
  key: string; // `${deviceId}:${fy}`
  lastSeq: number;
}

export interface CatalogueRow {
  key: 'current';
  etag: string | null;
  data: Catalogue;
  fetchedAt: string;
}

export class PosDB extends Dexie {
  meta!: EntityTable<MetaRow, 'key'>;
  catalogue!: EntityTable<CatalogueRow, 'key'>;
  counters!: EntityTable<CounterRow, 'key'>;
  bills!: EntityTable<LocalBill, 'id'>;

  constructor(name = 'chai-pos') {
    super(name);
    this.version(1).stores({
      meta: 'key',
      catalogue: 'key',
      counters: 'key',
      // [status+seq]: the outbox in invoice order; businessDate: today's bills
      bills: 'id, [status+seq], businessDate, status',
    });
  }

  async getMeta<T>(key: string): Promise<T | undefined> {
    return (await this.meta.get(key))?.value as T | undefined;
  }

  async setMeta(key: string, value: unknown): Promise<void> {
    if (value === undefined || value === null) await this.meta.delete(key);
    else await this.meta.put({ key, value });
  }

  pendingCount(): Promise<number> {
    return this.bills.where('status').equals('pending').count();
  }
}

export const db = new PosDB();

/**
 * Ask the browser not to clear our storage under disk pressure. Without this,
 * a full phone could silently delete the outbox and the invoice counter.
 * Installed PWAs are usually granted it; returns whether it was granted.
 */
export async function requestPersistentStorage(): Promise<boolean> {
  if (typeof navigator === 'undefined' || !navigator.storage?.persist) return false;
  if (await navigator.storage.persisted()) return true;
  return navigator.storage.persist();
}

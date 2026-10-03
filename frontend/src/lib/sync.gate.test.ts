/**
 * PHASE 2b GATE, against the REAL backend and database.
 *
 * 20 bills are made with no network at all. Then they are synced over a
 * deliberately broken connection, including the hardest case: the server SAVES
 * the bills but the reply is lost, so the tablet sends them again.
 *
 * Pass = the outbox empties, and the server holds each of the 20 bills exactly once.
 *
 * Runs only when GATE_API_URL is set (CI starts a backend; locally:
 *   GATE_API_URL=http://localhost:8000/api/v1 GATE_PASSWORD=... npx vitest run gate)
 */
import 'fake-indexeddb/auto';
import { describe, expect, it } from 'vitest';
import { Api, NetworkError } from './api';
import { resumeCounters, saveBill, type CartLine } from './billing';
import { refreshCatalogue } from './catalogue';
import { PosDB } from './db';
import { syncOnce } from './sync';
import type { Device } from './types';

const API = process.env.GATE_API_URL;
const PASSWORD = process.env.GATE_PASSWORD ?? 'devpass123';
const CASHIER = process.env.GATE_CASHIER ?? '9000000002';
const OWNER = process.env.GATE_OWNER ?? '9000000001';

describe.skipIf(!API)('Phase 2b gate: offline bills reach the real server exactly once', () => {
  it('20 offline bills, flaky network with lost replies, each stored once', async () => {
    const db = new PosDB(`gate-${Date.now()}`);
    const api = new Api({ baseUrl: API!, db });
    await api.login(CASHIER, PASSWORD);

    const devices = await api.get<Device[]>('/devices');
    const device = devices.find((d) => d.code === 'C1')!;
    const state = await api.get<{ last_seq_by_fy: Record<string, number> }>(
      `/devices/${device.id}/sync-state`,
    );
    await resumeCounters(db, device.id, state.last_seq_by_fy); // reruns don't clash
    const catalogue = (await refreshCatalogue(api, db))!;

    const ownerApi = new Api({ baseUrl: API!, db: new PosDB(`gate-owner-${Date.now()}`) });
    await ownerApi.login(OWNER, PASSWORD);
    type ServerBill = { id: string; totals_mismatch: boolean };
    const before = await ownerApi.get<ServerBill[]>('/bills');

    // ---- 1. Twenty sales with NO network: nothing may touch fetch ----
    let rngSeed = 2026;
    const rnd = () => ((rngSeed = (rngSeed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
    api.setFetch(() => Promise.reject(new TypeError('offline')));
    const items = catalogue.menu_items;
    const made = [];
    for (let i = 0; i < 20; i++) {
      const item = items[Math.floor(rnd() * items.length)];
      const mods = item.modifier_ids.filter(() => rnd() < 0.4);
      const cart: CartLine[] = [{ menuItemId: item.id, qty: 1 + Math.floor(rnd() * 3), modifierIds: mods }];
      made.push(
        await saveBill({
          db, deviceId: device.id, deviceCode: device.code, catalogue, cart,
          paymentMode: (['cash', 'upi', 'card'] as const)[i % 3],
        }),
      );
    }
    expect(await db.pendingCount()).toBe(20);
    await expect(syncOnce(api, db, device.id)).rejects.toBeInstanceOf(NetworkError);

    // ---- 2. Network back, but broken: 30% never arrive, 25% arrive but the reply is lost ----
    const realFetch = globalThis.fetch;
    let lostReplies = 0;
    let syncCalls = 0;
    api.setFetch(async (url, init) => {
      const r = rnd();
      if (String(url).includes('/sync/bills')) {
        syncCalls++;
        if (syncCalls > 1 && r < 0.3) throw new TypeError('request dropped');
        if (syncCalls === 1 || r < 0.55) { // the very first reply is always lost
          await realFetch(url, init); // the server stores the bills...
          lostReplies++;
          throw new TypeError('reply lost'); // ...but the tablet never hears back
        }
      }
      return realFetch(url, init);
    });

    let attempts = 0;
    while ((await db.pendingCount()) > 0 && attempts < 100) {
      attempts++;
      try {
        await syncOnce(api, db, device.id, 3); // small batches: many chances to fail
      } catch (e) {
        expect(e).toBeInstanceOf(NetworkError);
      }
    }

    // ---- 3. Verify ----
    expect(await db.pendingCount()).toBe(0);
    expect(lostReplies).toBeGreaterThan(0); // the hard case really happened
    const local = await db.bills.toArray();
    expect(local.every((b) => b.status === 'synced' && !b.totalsMismatch)).toBe(true);

    const after = await ownerApi.get<ServerBill[]>('/bills');
    expect(after.length - before.length).toBe(20);
    const serverIds = after.map((b) => b.id);
    for (const bill of made) {
      expect(serverIds.filter((id) => id === bill.id)).toHaveLength(1);
    }
    // Python and TypeScript agreed on every total.
    expect(after.filter((b) => made.some((m) => m.id === b.id)).every((b) => !b.totals_mismatch)).toBe(true);
    console.log(`gate: ${attempts} sync attempts, ${lostReplies} lost replies, 20/20 stored once`);
  }, 60_000);
});

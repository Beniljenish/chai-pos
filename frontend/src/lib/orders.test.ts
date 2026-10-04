import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import cases from '../../../shared/order_cases.json';
import type { Api } from './api';
import { PosDB } from './db';
import {
  act,
  billLines,
  liveOrder,
  liveOrders,
  nextKotNo,
  openOrder,
  pullLive,
  reduce,
  resetTick,
  sendKot,
  syncOrderEvents,
  type KotLineIn,
  type OrderEvent,
} from './orders';

describe('shared order rules (same cases as the server)', () => {
  for (const c of cases.cases) {
    it(c.name, () => {
      const state = reduce(c.events as OrderEvent[]) as unknown as Record<string, unknown>;
      const picked = Object.fromEntries(Object.keys(c.expect).map((k) => [k, state[k]]));
      expect(picked).toEqual(c.expect);
    });
  }
});

let db: PosDB;
beforeEach(() => {
  db = new PosDB(`orders-${Math.random()}`);
  // Tests use fixed times; without this, an earlier test's real clock (later
  // than 06:00 UTC on 4 Oct 2026) pushed them out of order.
  resetTick();
});

const tea = (qty: number, id = `l-${Math.random()}`): KotLineIn => ({
  line_id: id,
  menu_item_id: 'tea',
  name: 'Masala tea',
  qty,
  unit_price_paise: 2000,
  gst_rate_bp: 500,
  tax_inclusive: true,
});

describe('a table order on this device', () => {
  it('opens, sends KOTs, and shows the running order before anything is sent', async () => {
    const t0 = new Date('2026-10-04T06:00:00Z');
    const id = await openOrder(db, { orderType: 'dine_in', tableId: 't4', covers: 2 }, 'ravi', t0);
    await sendKot(db, id, 'C1-1', [tea(2)], 'ravi', new Date('2026-10-04T06:01:00Z'));
    const o = await liveOrder(db, id);
    expect(o?.state).toMatchObject({ status: 'open', table_id: 't4', covers: 2, opened_by: 'ravi' });
    expect(o?.state.lines.map((l) => l.qty)).toEqual([2]);
    expect(o?.unsent).toBe(2);
    expect(await db.pendingCount()).toBe(2); // in the sync badge with bills
  });

  it("this device's own actions keep their order even within one millisecond", async () => {
    const same = new Date('2026-10-04T06:00:00.000Z');
    const id = await openOrder(db, { orderType: 'dine_in', tableId: 't1' }, 'ravi', same);
    await sendKot(db, id, 'C1-1', [tea(2, 'x')], 'ravi', same);
    await act(db, id, 'cancel', { line_id: 'x', qty: 1, reason: 'one less' }, 'ravi', same);
    const state = (await liveOrder(db, id))!.state;
    expect(state.lines[0]).toMatchObject({ qty: 1, cancelled_qty: 1 });
  });

  it('numbers KOTs per device per day', async () => {
    const day1 = new Date('2026-10-04T06:00:00Z');
    expect(await nextKotNo(db, 'dev', 'C1', day1)).toBe('C1-1');
    expect(await nextKotNo(db, 'dev', 'C1', day1)).toBe('C1-2');
    expect(await nextKotNo(db, 'dev', 'C1', new Date('2026-10-05T06:00:00Z'))).toBe('C1-1');
  });

  it('settled or cancelled orders leave the floor', async () => {
    const a = await openOrder(db, { orderType: 'takeaway' }, 'ravi');
    const b = await openOrder(db, { orderType: 'dine_in', tableId: 't1' }, 'ravi');
    await act(db, a, 'settle', { bill_id: 'bill-1' }, 'ravi');
    await act(db, b, 'cancel_order', { reason: 'left' }, 'ravi');
    expect(await liveOrders(db)).toEqual([]);
  });

  it('bill lines keep the price the item was ordered at, and skip cancelled lines', async () => {
    const id = await openOrder(db, { orderType: 'dine_in', tableId: 't4' }, 'ravi');
    const keep = tea(3, 'keep');
    await sendKot(db, id, 'C1-1', [keep, tea(1, 'gone')], 'ravi');
    await act(db, id, 'cancel', { line_id: 'gone', qty: 1, reason: 'mistake' }, 'ravi');
    const state = (await liveOrder(db, id))!.state;
    const lines = billLines(state, (m) => (m === 'tea' ? 'recipe-v3' : null));
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ menu_item_id: 'tea', recipe_id: 'recipe-v3', qty: 3, unit_price_paise: 2000 });
  });
});

describe('syncing with other devices', () => {
  it('sends events and marks them sent; merges what other devices did', async () => {
    const id = await openOrder(db, { orderType: 'dine_in', tableId: 't4' }, 'ravi', new Date('2026-10-04T06:00:00Z'));
    await sendKot(db, id, 'C1-1', [tea(1, 'mine')], 'ravi', new Date('2026-10-04T06:01:00Z'));
    const sent: OrderEvent[] = [];
    const post = vi.fn(async (_path: string, body: { events: OrderEvent[] }) => {
      sent.push(...body.events);
      return { results: body.events.map((e) => ({ id: e.id, status: 'accepted', reason: null })) };
    });
    // The server knows our two events plus a waiter phone's KOT on the same table.
    const fromPhone: OrderEvent = {
      id: 'phone-1',
      order_id: id,
      kind: 'kot',
      at: '2026-10-04T06:05:00Z',
      by: 'arun',
      data: { kot_no: 'C2-1', lines: [tea(2, 'theirs')] },
    };
    const get = vi.fn(async () => ({
      server_time: '2026-10-04T06:06:00Z',
      orders: [{ id, status: 'open', events: [...sent, fromPhone] }],
    }));
    const api = { post, get } as unknown as Api;

    expect(await syncOrderEvents(api, db, 'dev')).toBe(2);
    expect(await db.pendingCount()).toBe(0);
    await pullLive(api, db);
    const o = (await liveOrder(db, id))!;
    expect(o.state.lines.map((l) => [l.line_id, l.qty])).toEqual([
      ['mine', 1],
      ['theirs', 2],
    ]);
    expect(o.unsent).toBe(0);

    // Later the table is settled on the counter tablet: it leaves this device's floor.
    get.mockResolvedValueOnce({ server_time: '2026-10-04T07:00:00Z', orders: [{ id, status: 'settled', events: null }] } as never);
    await pullLive(api, db);
    expect(await liveOrders(db)).toEqual([]);
    expect(await db.orderEvents.count()).toBe(0); // its sent events were cleaned up
    expect(get).toHaveBeenLastCalledWith('/orders/live?since=2026-10-04T06%3A06%3A00Z');
  });

  it('a refused event stays on the device with its reason', async () => {
    const id = await openOrder(db, { orderType: 'takeaway' }, 'ravi');
    const api = {
      post: vi.fn(async (_p: string, body: { events: OrderEvent[] }) => ({
        results: body.events.map((e) => ({ id: e.id, status: 'rejected', reason: 'device_clock_ahead' })),
      })),
    } as unknown as Api;
    await syncOrderEvents(api, db, 'dev');
    const row = (await db.orderEvents.toArray())[0];
    expect([row.orderId, row.status, row.reason]).toEqual([id, 'rejected', 'device_clock_ahead']);
  });
});

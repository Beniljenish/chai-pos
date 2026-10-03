import { describe, expect, it } from 'vitest';
import { billSummaryRows, kotRows } from './escpos';
import { reduce, type LiveOrder, type OrderEvent } from './orders';
import { floorModel, hasTables, kitchenTickets, kotLinesFromCart, orderLabel, priceOrder } from './table';
import { testCatalogue } from './test-fixtures';
import type { Catalogue } from './types';

const catalogue: Catalogue = {
  ...testCatalogue,
  areas: [
    {
      id: 'hall',
      name: 'Hall',
      sort: 0,
      is_active: true,
      tables: [
        { id: 't1', name: 'T1', seats: 4, sort: 0, is_active: true },
        { id: 't2', name: 'T2', seats: 4, sort: 1, is_active: true },
        { id: 't3', name: 'T3', seats: 2, sort: 2, is_active: false },
      ],
    },
    { id: 'roof', name: 'Roof', sort: 1, is_active: false, tables: [{ id: 'r1', name: 'R1', seats: 4, sort: 0, is_active: true }] },
  ],
};

let n = 0;
const ev = (kind: OrderEvent['kind'], data: Record<string, unknown>, at: string): OrderEvent => ({
  id: `e${String(++n).padStart(4, '0')}`,
  kind,
  at,
  by: 'ravi',
  data,
});

function order(id: string, events: OrderEvent[]): LiveOrder {
  return { id, state: reduce(events), unsent: 0 };
}

describe('a draft round becomes KOT lines', () => {
  it('freezes name, price, GST and options; keeps the cook note', () => {
    let i = 0;
    const lines = kotLinesFromCart(
      [
        { menuItemId: 'tea', qty: 2, modifierIds: [] },
        { menuItemId: 'tea', qty: 1, modifierIds: ['large'], note: '  less sugar ' },
      ],
      catalogue,
      () => `line-${++i}`,
    );
    expect(lines).toEqual([
      expect.objectContaining({ line_id: 'line-1', name: 'Masala tea', qty: 2, unit_price_paise: 2000, gst_rate_bp: 500, tax_inclusive: true, modifiers: [], note: '' }),
      expect.objectContaining({ line_id: 'line-2', qty: 1, note: 'less sugar' }),
    ]);
    expect(lines[1].modifiers?.[0]).toMatchObject({ modifier_id: 'large', price_delta_paise: 1000 });
  });

  it('an item taken off the menu cannot be sent', () => {
    expect(() => kotLinesFromCart([{ menuItemId: 'gone', qty: 1, modifierIds: [] }], catalogue)).toThrow(/no longer on the menu/);
  });
});

describe('what the table owes', () => {
  it('prices sent lines by the counter GST rules, at the price they were ordered', () => {
    const lines = kotLinesFromCart([{ menuItemId: 'tea', qty: 1, modifierIds: ['large'] }, { menuItemId: 'tea', qty: 2, modifierIds: [] }], catalogue);
    lines[1].unit_price_paise = 1500; // the menu price was lower when this round went in
    const state = reduce([
      ev('open', { order_type: 'dine_in', table_id: 't1' }, '2026-10-04T06:00:00Z'),
      ev('kot', { kot_no: 'C1-1', lines }, '2026-10-04T06:01:00Z'),
    ]);
    const { totals, lines: billed } = priceOrder(state, catalogue);
    expect(totals?.total).toBe(3000 + 3000);
    expect(billed.map((l) => l.recipe_id)).toEqual(['r-tea', 'r-tea']);
    // A ₹30 large tea at 5% inclusive: 28.57 + 0.71 + 0.71 (ROUND_HALF_UP per line)
    expect(billed[0].totals).toMatchObject({ taxable: 2858, cgst: 71, sgst: 71, total: 3000 });
  });

  it('nothing sent, or everything cancelled: nothing to charge', () => {
    const lines = kotLinesFromCart([{ menuItemId: 'tea', qty: 1, modifierIds: [] }], catalogue, () => 'x');
    const state = reduce([
      ev('open', { order_type: 'takeaway' }, '2026-10-04T06:00:00Z'),
      ev('kot', { kot_no: 'C1-1', lines }, '2026-10-04T06:01:00Z'),
      ev('cancel', { line_id: 'x', qty: 1, reason: 'left' }, '2026-10-04T06:02:00Z'),
    ]);
    expect(priceOrder(state, catalogue).totals).toBeNull();
  });
});

describe('the floor', () => {
  const now = Date.parse('2026-10-04T07:00:00Z');
  const tea = (id: string) => kotLinesFromCart([{ menuItemId: 'tea', qty: 2, modifierIds: [] }], catalogue, () => id);

  it('shows each active table free, running or billed, with time and amount', () => {
    const running = order('o1', [
      ev('open', { order_type: 'dine_in', table_id: 't1', covers: 3 }, '2026-10-04T06:35:00Z'),
      ev('kot', { kot_no: 'C1-1', lines: tea('a') }, '2026-10-04T06:36:00Z'),
    ]);
    const billed = order('o2', [
      ev('open', { order_type: 'dine_in', table_id: 't2' }, '2026-10-04T06:50:00Z'),
      ev('kot', { kot_no: 'C1-2', lines: tea('b') }, '2026-10-04T06:51:00Z'),
      ev('bill_printed', {}, '2026-10-04T06:58:00Z'),
    ]);
    const takeaway = order('o3', [ev('open', { order_type: 'takeaway', customer_name: 'Priya' }, '2026-10-04T06:55:00Z')]);
    const floor = floorModel(catalogue, [running, billed, takeaway], now);

    expect(floor.areas.map((a) => a.name)).toEqual(['Hall']); // the switched-off area is hidden
    expect(floor.areas[0].tables.map((t) => [t.name, t.status, t.minutes, t.totalPaise, t.covers])).toEqual([
      ['T1', 'running', 25, 4000, 3],
      ['T2', 'billed', 10, 4000, 0],
    ]);
    expect(floor.other.map((o) => o.id)).toEqual(['o3']);
  });

  it('an order on a table that was since switched off is not lost', () => {
    const lost = order('o4', [ev('open', { order_type: 'dine_in', table_id: 't3' }, '2026-10-04T06:00:00Z')]);
    expect(floorModel(catalogue, [lost], now).other.map((o) => o.id)).toEqual(['o4']);
  });

  it('names orders the way staff say them', () => {
    const s = (data: Record<string, unknown>, kot = false) =>
      reduce([
        ev('open', data, '2026-10-04T06:00:00Z'),
        ...(kot ? [ev('kot', { kot_no: 'C1-9', lines: tea(`k${n}`) }, '2026-10-04T06:01:00Z')] : []),
      ]);
    expect(orderLabel(catalogue, s({ order_type: 'dine_in', table_id: 't2' }))).toBe('T2');
    expect(orderLabel(catalogue, s({ order_type: 'takeaway', customer_name: 'Priya' }))).toBe('Takeaway: Priya');
    expect(orderLabel(catalogue, s({ order_type: 'delivery' }, true))).toBe('Delivery #C1-9');
    expect(hasTables(catalogue)).toBe(true);
    expect(hasTables({ ...catalogue, areas: [] })).toBe(false);
  });
});

describe('printing for table service', () => {
  it('the KOT has quantities first and no prices', () => {
    const rows = kotRows(
      {
        kind: 'KOT',
        kotNo: 'C1-4',
        label: 'T4',
        at: '2026-10-04T03:05:00Z',
        byName: 'Ravi',
        covers: 2,
        lines: [
          { name: 'Masala tea', qty: 2, modifiers: [{ name: 'Large' }], note: 'less sugar' },
          { name: 'Bun butter jam with extra cheese', qty: 1 },
        ],
      },
      32,
    );
    expect(rows.map((r) => r.text)).toEqual([
      'KOT C1-4',
      'T4',
      '-'.repeat(32),
      '04 Oct 2026, 08:35 am       Ravi',
      'Guests: 2',
      '-'.repeat(32),
      '2   Masala tea',
      '    + Large',
      '    * less sugar',
      '1   Bun butter jam with extra',
      '    cheese',
    ]);
    expect(rows.every((r) => !r.text.includes('Rs.'))).toBe(true);
    expect(rows.every((r) => r.text.length <= (r.big ? 16 : 32))).toBe(true);
  });

  it('a cancel ticket says what to stop making and why', () => {
    const rows = kotRows(
      { kind: 'CANCEL', kotNo: 'C1-4', label: 'T4', at: '2026-10-04T03:05:00Z', byName: 'Ravi', lines: [{ name: 'Masala tea', qty: 1 }], reason: 'Wrong item entered' },
      32,
    );
    expect(rows[0]).toMatchObject({ text: 'CANCEL C1-4', big: true });
    expect(rows.map((r) => r.text)).toContain('-1  Masala tea');
    expect(rows.at(-1)?.text).toBe('Reason: Wrong item entered');
  });

  it('the bill at the table has the total but no invoice number', () => {
    const lines = kotLinesFromCart([{ menuItemId: 'tea', qty: 2, modifierIds: [] }], catalogue, () => 'z');
    const state = reduce([
      ev('open', { order_type: 'dine_in', table_id: 't1', covers: 2 }, '2026-10-04T03:00:00Z'),
      ev('kot', { kot_no: 'C1-1', lines }, '2026-10-04T03:01:00Z'),
    ]);
    const priced = priceOrder(state, catalogue);
    const rows = billSummaryRows(
      { label: 'T1', covers: 2, at: '2026-10-04T03:05:00Z', copy: 2, gstType: 'regular', lines: priced.lines, totals: priced.totals! },
      catalogue.shop,
      32,
    );
    const text = rows.map((r) => r.text);
    expect(text).toContain('(Copy 2)');
    expect(text).toContain('T1                      Guests 2');
    expect(text).toContain('CGST @2.5%               Rs.0.95');
    expect(rows.find((r) => r.big && r.text.startsWith('TOTAL'))?.text).toBe('TOTAL      Rs.40');
    expect(text.some((t) => /^No\./.test(t))).toBe(false);
  });
});

describe('the kitchen screen', () => {
  const now = Date.parse('2026-10-04T07:00:00Z');
  const two = (a: string, b: string) => [
    ...kotLinesFromCart([{ menuItemId: 'tea', qty: 2, modifierIds: ['large'], note: 'hot' }], catalogue, () => a),
    ...kotLinesFromCart([{ menuItemId: 'tea', qty: 1, modifierIds: [] }], catalogue, () => b),
  ];

  it('lists what is left to make, oldest KOT first; ready and cancelled lines drop off', () => {
    const t1 = order('k1', [
      ev('open', { order_type: 'dine_in', table_id: 't1' }, '2026-10-04T06:30:00Z'),
      ev('kot', { kot_no: 'C1-1', lines: two('a', 'b') }, '2026-10-04T06:31:00Z'),
      ev('ready', { line_ids: ['a'] }, '2026-10-04T06:40:00Z'),
      ev('kot', { kot_no: 'C1-3', lines: two('c', 'd') }, '2026-10-04T06:55:00Z'),
      ev('cancel', { line_id: 'd', qty: 1, reason: 'no' }, '2026-10-04T06:56:00Z'),
    ]);
    const take = order('k2', [
      ev('open', { order_type: 'takeaway', customer_name: 'Priya' }, '2026-10-04T06:40:00Z'),
      ev('kot', { kot_no: 'C2-1', lines: two('e', 'f') }, '2026-10-04T06:41:00Z'),
      ev('ready', { line_ids: ['e', 'f'] }, '2026-10-04T06:50:00Z'),
    ]);
    const tickets = kitchenTickets(catalogue, [take, t1], now);
    expect(tickets.map((t) => [t.label, t.kotNo, t.minutes, t.lines.map((l) => l.line_id)])).toEqual([
      ['T1', 'C1-1', 29, ['b']],
      ['T1', 'C1-3', 5, ['c']],
    ]);
    expect(tickets[1].lines[0]).toMatchObject({ qty: 2, modifiers: ['Large'], note: 'hot' });
  });
});

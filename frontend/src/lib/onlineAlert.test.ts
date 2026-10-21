import { describe, expect, it } from 'vitest';
import { spotNewOnlineOrders } from './onlineAlert';

const order = (id: string, name: string, status = 'open') => ({ id, state: { customer_name: name, status } });

describe('spotNewOnlineOrders', () => {
  it('learns the queue on the first look without ringing', () => {
    const r = spotNewOnlineOrders(null, [order('a', 'JT-1 Ravi'), order('b', 'JT-2 Priya')]);
    expect(r.fresh).toEqual([]);
    expect([...r.known].sort()).toEqual(['a', 'b']);
  });

  it('rings once for an order that was not there before', () => {
    const first = spotNewOnlineOrders(null, [order('a', 'JT-1 Ravi')]);
    const second = spotNewOnlineOrders(first.known, [order('a', 'JT-1 Ravi'), order('b', 'JT-2 Priya')]);
    expect(second.fresh.map((o) => o.id)).toEqual(['b']);
    const third = spotNewOnlineOrders(second.known, [order('a', 'JT-1 Ravi'), order('b', 'JT-2 Priya')]);
    expect(third.fresh).toEqual([]);
  });

  it('ignores counter orders, tables and orders that are already billed or cancelled', () => {
    const r = spotNewOnlineOrders(new Set(), [
      order('t', 'Ravi'), // a takeaway taken at the counter: no token in the name
      order('s', 'JT-3 Ravi', 'settled'),
      order('c', 'JT-4 Ravi', 'cancelled'),
    ]);
    expect(r.fresh).toEqual([]);
  });

  it('does not ring again for an order that left and came back', () => {
    const a = spotNewOnlineOrders(null, [order('a', 'JT-1 Ravi')]);
    const gone = spotNewOnlineOrders(a.known, []);
    const back = spotNewOnlineOrders(gone.known, [order('a', 'JT-1 Ravi')]);
    expect(back.fresh).toEqual([]);
  });
});

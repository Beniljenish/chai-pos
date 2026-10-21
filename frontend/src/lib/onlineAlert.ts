/** Spotting a customer's order that has just arrived, so the till can ring. Pure, so it is tested
 * on its own (onlineAlert.test.ts). */
import { onlineToken } from './table';

interface OrderLike {
  id: string;
  state: { customer_name: string; status: string };
}

/** Compare the open online orders now with the ones already seen. The first look (made after the
 * tablet's first sync) only learns what is there: a tablet that has just been switched on must not
 * ring for the whole queue, which is already on its Tables screen. */
export function spotNewOnlineOrders<T extends OrderLike>(
  known: ReadonlySet<string> | null,
  orders: T[],
): { known: Set<string>; fresh: T[] } {
  const open = orders.filter((o) => o.state.status === 'open' && onlineToken(o.state) !== null);
  const next = new Set(open.map((o) => o.id));
  if (known === null) return { known: next, fresh: [] };
  return { known: new Set([...known, ...next]), fresh: open.filter((o) => !known.has(o.id)) };
}

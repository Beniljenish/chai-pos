/** What a customer's phone says to the server: no login, no tokens, no offline queue.
 * An order is placed or it is not; the page says which. */
import type { OrderStatus, PublicItem } from './foodcourt';
import type { GstType } from './gst';

export interface PublicCourt {
  name: string;
  outlets: { id: string; name: string; open: boolean }[];
}

export interface PublicMenu {
  outlet: string;
  open: boolean;
  gst_type: GstType;
  items: PublicItem[];
}

export interface PlacedOrder {
  order_id: string;
  token: string;
  status_key: string;
}

export interface PublicOrder {
  token: string;
  outlet: string;
  status: OrderStatus;
  items: { name: string; qty: number }[];
  total_paise: number;
}

export class PublicError extends Error {
  status: number;
  code: string | undefined;
  names: string[] | undefined;
  constructor(status: number, code?: string, names?: string[]) {
    super(code ?? `HTTP ${status}`);
    this.status = status;
    this.code = code;
    this.names = names;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${__API_URL__}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });
  if (!res.ok) {
    let code: string | undefined;
    let names: string[] | undefined;
    try {
      const detail = (await res.json()).detail;
      if (detail && typeof detail === 'object') {
        code = detail.code;
        names = detail.names;
      }
    } catch {
      /* not JSON: the status says enough */
    }
    throw new PublicError(res.status, code, names);
  }
  return (await res.json()) as T;
}

const slugPath = (slug: string) => `/public/courts/${encodeURIComponent(slug)}`;

export const publicApi = {
  court: (slug: string) => call<PublicCourt>(slugPath(slug)),
  menu: (slug: string, outletId: string) => call<PublicMenu>(`${slugPath(slug)}/outlets/${outletId}/menu`),
  order: (key: string) => call<PublicOrder>(`/public/orders/${key}`),
  place: (
    slug: string,
    outletId: string,
    body: {
      request_id: string;
      name: string;
      phone: string;
      note: string;
      message_ok: boolean;
      items: { menu_item_id: string; qty: number }[];
    },
  ) => call<PlacedOrder>(`${slugPath(slug)}/outlets/${outletId}/orders`, { method: 'POST', body: JSON.stringify(body) }),
};

/** What a customer's phone says to the server. Browsing is open to anyone; ordering and
 * the account need the customer's own token (a different kind from staff and admin tokens).
 * No offline queue: an order is placed or it is not, and the page says which. */
import type { OrderStatus, PublicItem } from './foodcourt';
import type { GstType } from './gst';

export interface PublicCourt {
  name: string;
  location: string;
  /** Whether "pay online" may be offered (the server has payment keys). */
  online_payment: boolean;
  outlets: { id: string; name: string; open: boolean }[];
}

export interface CourtRow {
  name: string;
  slug: string;
  location: string;
  outlets: number;
  open: number;
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
  paid_online: boolean;
}

/** One online payment for a cart, and (once it is paid) what became of each outlet's part. */
export interface CheckoutView {
  id: string;
  status: 'created' | 'paid' | 'failed';
  amount_paise: number;
  razorpay_order_id: string;
  error: string;
  fulfilled: boolean;
  refunded_paise: number;
  orders: {
    outlet: string;
    amount_paise: number;
    status_key: string | null;
    token: string | null;
    error: string | null;
    message: string | null;
    refunded: boolean | null;
  }[];
}

export interface CheckoutBody {
  checkout_id: string;
  slug: string;
  message_ok: boolean;
  orders: {
    outlet_id: string;
    request_id: string;
    note: string;
    items: { menu_item_id: string; qty: number }[];
  }[];
}

export interface Account {
  name: string;
  phone: string;
  must_change_password: boolean;
}

export interface Signed {
  access_token: string;
  account: Account;
}

export interface HistoryRow {
  token: string;
  outlet: string;
  court: string;
  court_slug: string;
  placed_at: string;
  status: OrderStatus;
  items: { name: string; qty: number }[];
  total_paise: number;
  status_key: string;
}

export class PublicError extends Error {
  status: number;
  code: string | undefined;
  names: string[] | undefined;
  /** The server's own words (a lockout says how many minutes), when it gave any. */
  message: string;
  constructor(status: number, code?: string, names?: string[], message?: string) {
    super(code ?? `HTTP ${status}`);
    this.status = status;
    this.code = code;
    this.names = names;
    this.message = message ?? '';
  }
}

async function call<T>(path: string, init?: RequestInit, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${__API_URL__}${path}`, { ...init, headers, cache: 'no-store' });
  if (!res.ok) {
    let code: string | undefined;
    let names: string[] | undefined;
    let message: string | undefined;
    try {
      const detail = (await res.json()).detail;
      if (typeof detail === 'string') message = detail;
      else if (detail && typeof detail === 'object') {
        code = detail.code;
        names = detail.names;
        message = detail.message;
      }
    } catch {
      /* not JSON: the status says enough */
    }
    throw new PublicError(res.status, code, names, message);
  }
  return (await res.json()) as T;
}

const slugPath = (slug: string) => `/public/courts/${encodeURIComponent(slug)}`;
const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const publicApi = {
  // ---- account
  signup: (name: string, phone: string, password: string) =>
    call<Signed>('/customer/signup', post({ name, phone, password })),
  login: (phone: string, password: string) => call<Signed>('/customer/login', post({ phone, password })),
  me: (token: string) => call<Account>('/customer/me', undefined, token),
  changePassword: (token: string, current_password: string, new_password: string) =>
    call<Signed>('/customer/password', post({ current_password, new_password }), token),
  history: (token: string) => call<{ orders: HistoryRow[] }>('/customer/orders', undefined, token),
  // ---- browsing
  courts: (token: string) => call<{ courts: CourtRow[] }>('/public/courts', undefined, token),
  court: (slug: string) => call<PublicCourt>(slugPath(slug)),
  menu: (slug: string, outletId: string) => call<PublicMenu>(`${slugPath(slug)}/outlets/${outletId}/menu`),
  order: (key: string) => call<PublicOrder>(`/public/orders/${key}`),
  // ---- paying in the app: one payment for the whole cart, orders placed once it is paid
  checkout: (token: string, body: CheckoutBody) => call<CheckoutView>('/customer/checkout', post(body), token),
  checkoutStatus: (token: string, id: string) => call<CheckoutView>(`/customer/checkout/${id}`, undefined, token),
  // ---- ordering: the name and phone on the order are the account's
  place: (
    token: string,
    slug: string,
    outletId: string,
    body: { request_id: string; note: string; message_ok: boolean; items: { menu_item_id: string; qty: number }[] },
  ) => call<PlacedOrder>(`${slugPath(slug)}/outlets/${outletId}/orders`, post(body), token),
};

/** Razorpay's page for one payment. It lives on the API (not in this app) so that no
 * payment script runs where the customer's login is kept; the app opens it in a new tab. */
export const payPageUrl = (razorpayOrderId: string): string =>
  `${__API_URL__}/payments/razorpay/customer-checkout?order_id=${encodeURIComponent(razorpayOrderId)}`;

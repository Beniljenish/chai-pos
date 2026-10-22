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
  outlets: { id: string; name: string; open: boolean; prep_minutes: number | null }[];
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
  /** Set while the outlet has paused new orders because it is busy (ISO time it ends). */
  paused_until?: string | null;
  /** The outlet's own promise of how long an order usually takes (null: not said). */
  prep_minutes: number | null;
  gst_type: GstType;
  items: PublicItem[];
}

/** What the food court's display shows: tokens only. */
export interface Board {
  court: string;
  ready: { token: string; outlet: string }[];
  making: { token: string; outlet: string }[];
}

/** A dish this customer keeps ordering at an outlet, in the quantity they usually take. */
export interface Usual {
  menu_item_id: string;
  modifier_ids: string[];
  qty: number;
  name: string;
  times: number;
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
  prep_minutes: number | null;
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
    pickup_at: string | null;
    table_name: string;
    coupon_code: string;
    items: { menu_item_id: string; qty: number; modifier_ids: string[] }[];
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
  /** What "order again" puts back in the cart. */
  lines: { menu_item_id: string; qty: number; modifier_ids: string[] }[];
  outlet_id: string;
  total_paise: number;
  status_key: string;
  paid_online: boolean;
  rating: number | null;
}

export interface Favourite {
  menu_item_id: string;
  name: string;
  name_ta?: string;
  price_paise: number;
  photo_url: string;
  is_veg: boolean;
  sold_out: boolean;
  outlet_id: string;
  outlet: string;
  court: string;
  court_slug: string;
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
  signup: (name: string, phone: string, password: string, code = '') =>
    call<Signed>('/customer/signup', post({ name, phone, password, code })),
  /** Whether sign-up asks for a code sent to the mobile number (only when the server can send one). */
  verification: () => call<{ required: boolean }>('/customer/verification'),
  /** Ask for a code. `dev_code` comes back only in local test mode, where nothing is really sent. */
  sendCode: (phone: string, purpose: 'signup' | 'reset') =>
    call<{ sent: boolean; cooldown_seconds: number; dev_code?: string }>('/customer/phone/code', post({ phone, purpose })),
  resetPassword: (phone: string, code: string, new_password: string) =>
    call<Signed>('/customer/password/reset', post({ phone, code, new_password })),
  login: (phone: string, password: string) => call<Signed>('/customer/login', post({ phone, password })),
  me: (token: string) => call<Account>('/customer/me', undefined, token),
  changePassword: (token: string, current_password: string, new_password: string) =>
    call<Signed>('/customer/password', post({ current_password, new_password }), token),
  history: (token: string) => call<{ orders: HistoryRow[] }>('/customer/orders', undefined, token),
  // ---- favourites, ratings, phone notifications
  favourites: (token: string) => call<{ favourites: Favourite[] }>('/customer/favourites', undefined, token),
  addFavourite: (token: string, itemId: string) =>
    call<{ favourites: Favourite[] }>(`/customer/favourites/${itemId}`, { method: 'PUT' }, token),
  removeFavourite: (token: string, itemId: string) =>
    call<{ favourites: Favourite[] }>(`/customer/favourites/${itemId}`, { method: 'DELETE' }, token),
  myRating: (token: string, key: string) =>
    call<{ rating: number | null; comment: string }>(`/customer/orders/${key}/rating`, undefined, token),
  rate: (token: string, key: string, rating: number, comment: string) =>
    call<{ rating: number }>(`/customer/orders/${key}/rating`, post({ rating, comment }), token),
  pushKey: (token: string) => call<{ public_key: string | null }>('/customer/push/key', undefined, token),
  pushSubscribe: (token: string, sub: { endpoint: string; keys: { p256dh: string; auth: string } }) =>
    call<{ ok: boolean }>('/customer/push/subscribe', post(sub), token),
  // ---- browsing
  courts: (token: string) => call<{ courts: CourtRow[] }>('/public/courts', undefined, token),
  court: (slug: string) => call<PublicCourt>(slugPath(slug)),
  menu: (slug: string, outletId: string) => call<PublicMenu>(`${slugPath(slug)}/outlets/${outletId}/menu`),
  slots: (slug: string, outletId: string) =>
    call<{ enabled: boolean; slots: { at: string; full: boolean }[] }>(`${slugPath(slug)}/outlets/${outletId}/slots`),
  board: (slug: string) => call<Board>(`${slugPath(slug)}/board`),
  order: (key: string) => call<PublicOrder>(`/public/orders/${key}`),
  /** What a code would take off this cart at this outlet (nothing is used up yet). */
  couponCheck: (
    token: string,
    body: { slug: string; outlet_id: string; code: string; items: { menu_item_id: string; qty: number; modifier_ids: string[] }[] },
  ) => call<{ outlet: string; discount_paise: number; total_paise: number }>('/customer/coupon-check', post(body), token),
  usual: (token: string, outletId: string) =>
    call<{ usual: Usual[] }>(`/customer/usual?outlet_id=${encodeURIComponent(outletId)}`, undefined, token),
  // ---- paying in the app: one payment for the whole cart, orders placed once it is paid
  checkout: (token: string, body: CheckoutBody) => call<CheckoutView>('/customer/checkout', post(body), token),
  checkoutStatus: (token: string, id: string) => call<CheckoutView>(`/customer/checkout/${id}`, undefined, token),
  // ---- ordering: the name and phone on the order are the account's
  place: (
    token: string,
    slug: string,
    outletId: string,
    body: {
      request_id: string;
      note: string;
      message_ok: boolean;
      pickup_at: string | null;
      table_name: string;
      coupon_code: string;
      items: { menu_item_id: string; qty: number; modifier_ids: string[] }[];
    },
  ) => call<PlacedOrder>(`${slugPath(slug)}/outlets/${outletId}/orders`, post(body), token),
};

/** Razorpay's page for one payment. It lives on the API (not in this app) so that no
 * payment script runs where the customer's login is kept; the app opens it in a new tab. */
export const payPageUrl = (razorpayOrderId: string): string =>
  `${__API_URL__}/payments/razorpay/customer-checkout?order_id=${encodeURIComponent(razorpayOrderId)}`;

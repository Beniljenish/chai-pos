/** The super admin's calls (/api/v1/platform). Its own small client: a super admin has no
 * shop, no tablet and no offline queue, and its token lives only in this browser tab. */

import type { Statement } from './statement';

export interface AdminOutlet {
  id: string;
  name: string;
  owner_name: string;
  owner_phone: string;
  accepting_orders: boolean;
  prep_minutes: number | null;
  rating: number | null;
  rating_count: number;
}

export interface AdminCourt {
  id: string;
  name: string;
  slug: string;
  location: string;
  outlets: AdminOutlet[];
}

export interface OutletMoney {
  court_id: string;
  court: string;
  outlet_id: string;
  outlet: string;
  orders: number;
  paid_paise: number;
  settled_paise: number;
  owed_paise: number;
  fee_bp: number;
  fee_paise: number;
  net_paise: number;
}

export interface RefundDue {
  ref: string;
  why: string;
  outlet: string;
  token: string | null;
  customer: string;
  phone: string;
  amount_paise: number;
}

export class AdminError extends Error {
  status: number;
  code: string | undefined;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const KEY = 'taptallow-admin-token';

export function savedToken(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function saveToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* private window: they sign in again after a reload */
  }
}

async function call<T>(path: string, token: string | null, init?: RequestInit): Promise<T> {
  const res = await fetch(`${__API_URL__}/platform${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    cache: 'no-store',
  });
  if (!res.ok) {
    let message = `Something went wrong (${res.status}).`;
    let code: string | undefined;
    try {
      const detail = (await res.json()).detail;
      if (typeof detail === 'string') message = detail;
      else if (detail && typeof detail === 'object') {
        message = detail.message ?? message;
        code = detail.code;
      } else if (Array.isArray(detail)) message = 'Please check what you typed.';
    } catch {
      /* keep the generic message */
    }
    throw new AdminError(res.status, message, code);
  }
  return (await res.json()) as T;
}

const body = (b: unknown) => ({ method: 'POST', body: JSON.stringify(b) });

export const adminApi = {
  login: (phone: string, password: string) =>
    call<{ access_token: string; name: string }>('/login', null, body({ phone, password })),
  courts: (t: string) => call<{ courts: AdminCourt[] }>('/courts', t),
  createCourt: (t: string, name: string, location: string) =>
    call<{ courts: AdminCourt[] }>('/courts', t, body({ name, location })),
  onlineMoney: (t: string) => call<{ outlets: OutletMoney[]; refunds_due: RefundDue[] }>('/online-money', t),
  settle: (t: string, courtId: string, outletId: string, amountPaise: number, note: string) =>
    call<{ outlets: OutletMoney[] }>(`/courts/${courtId}/outlets/${outletId}/settlements`, t, body({ amount_paise: amountPaise, note })),
  setFee: (t: string, courtId: string, outletId: string, feeBp: number) =>
    call<{ outlets: OutletMoney[] }>(`/courts/${courtId}/outlets/${outletId}/fee`, t, {
      method: 'PATCH',
      body: JSON.stringify({ fee_bp: feeBp }),
    }),
  statement: (t: string, courtId: string, outletId: string, from: string, to: string) =>
    call<Statement>(`/courts/${courtId}/outlets/${outletId}/statement?from=${from}&to=${to}`, t),
  refund: (t: string, ref: string) => call<{ refunds_due: RefundDue[] }>('/refunds', t, body({ ref })),
  /** A forgotten customer password: returns a temporary one, once, for the admin to read out. */
  resetCustomer: (t: string, phone: string) =>
    call<{ name: string; phone: string; temporary_password: string }>('/customers/reset-password', t, body({ phone })),
  addOutlet: (
    t: string,
    courtId: string,
    o: { shop_name: string; owner_name: string; owner_phone: string; password: string | null; sample_menu: boolean },
  ) => call<{ courts: AdminCourt[] }>(`/courts/${courtId}/outlets`, t, body(o)),
  attach: (t: string, courtId: string, ownerPhone: string) =>
    call<{ courts: AdminCourt[] }>(`/courts/${courtId}/outlets/attach`, t, body({ owner_phone: ownerPhone })),
  setAccepting: (t: string, courtId: string, outletId: string, on: boolean) =>
    call<{ courts: AdminCourt[] }>(`/courts/${courtId}/outlets/${outletId}`, t, {
      method: 'PATCH',
      body: JSON.stringify({ accepting_orders: on }),
    }),
  remove: (t: string, courtId: string, outletId: string) =>
    call<{ courts: AdminCourt[] }>(`/courts/${courtId}/outlets/${outletId}`, t, { method: 'DELETE' }),
};

/** Whether this server is in local test mode (the admin signs in by phone alone). */
export async function devLoginOn(): Promise<boolean> {
  try {
    const r = await fetch(`${__API_URL__}/auth/dev-login`);
    return r.ok && (await r.json()).enabled === true;
  } catch {
    return false;
  }
}

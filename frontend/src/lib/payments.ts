/**
 * Online payment of a saved bill through Razorpay (README, "Phase 8a").
 *
 * The bill is saved on the tablet first, as always. Paying online needs it on
 * the server, so the order is asked for, and if the server does not have the
 * bill yet, the tablet syncs and asks once more. Checkout itself runs on a page
 * served by the API (not inside this app, which allows no third-party script),
 * opened in a new tab; the till watches the payment's status on the server.
 */
import { HttpError, type Api } from './api';

export type OnlineMethod = 'upi' | 'card';
export type OnlineStatus = 'created' | 'paid' | 'failed';

export interface OnlineOrder {
  razorpay_order_id: string;
  amount_paise: number;
  method: OnlineMethod;
  status: OnlineStatus;
}

export interface OnlineState {
  status: OnlineStatus;
  paid_paise: number | null;
  error: string;
}

const detail = (e: unknown) => (e instanceof HttpError && typeof e.detail === 'string' ? e.detail : null);

/** Ask for the Razorpay order; if the bill has not reached the server, sync and ask again once. */
export async function orderFor(
  api: Pick<Api, 'post'>,
  syncNow: () => Promise<void>,
  billId: string,
  method: OnlineMethod,
): Promise<OnlineOrder> {
  const ask = () => api.post<OnlineOrder>('/payments/razorpay/order', { bill_id: billId, method });
  try {
    return await ask();
  } catch (e) {
    if (detail(e) !== 'bill_not_on_server') throw e;
    await syncNow();
    return ask();
  }
}

export const checkoutUrl = (apiBase: string, orderId: string) =>
  `${apiBase.replace(/\/$/, '')}/payments/razorpay/checkout?order_id=${encodeURIComponent(orderId)}`;

export async function onlineStatus(api: Pick<Api, 'get'>, orderId: string): Promise<OnlineState> {
  return api.get<OnlineState>(`/payments/razorpay/status?order_id=${encodeURIComponent(orderId)}`);
}

/** What the cashier is told when an online payment cannot start. */
export function explainOnline(e: unknown): string {
  switch (detail(e)) {
    case 'bill_not_on_server':
      return 'The bill has not reached the server yet. Check the internet and try again.';
    case 'online_payments_off':
      return 'Online payment is not set up for this shop.';
    case 'already_paid':
      return 'This bill is already paid.';
    case 'bill_void':
      return 'This bill was voided.';
    case 'razorpay_refused':
      return 'Razorpay did not accept the payment request. Try again, or take the payment another way.';
    default:
      return 'Online payment needs internet. Try again, or take the payment another way.';
  }
}

export const PROBLEM_LABELS: Record<string, string> = {
  not_paid: 'Not paid online',
  amount_mismatch: 'Paid a different amount',
  refund_due: 'Paid, then voided: refund due',
};

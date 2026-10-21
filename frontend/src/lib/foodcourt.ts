/** The customer's side of a food court order: pure helpers, tested in foodcourt.test.ts. */
import { computeBill, type GstType } from './gst';

export interface PublicItem {
  id: string;
  name: string;
  category: string;
  price_paise: number;
  gst_rate_bp: number;
  tax_inclusive: boolean;
  sold_out: boolean;
}

/** menu item id -> how many */
export type Cart = Record<string, number>;

export const MAX_QTY = 20;

export function changeQty(cart: Cart, id: string, delta: number): Cart {
  const next = Math.max(0, Math.min(MAX_QTY, (cart[id] ?? 0) + delta));
  const { [id]: _gone, ...rest } = cart;
  return next === 0 ? rest : { ...rest, [id]: next };
}

export const cartCount = (cart: Cart): number => Object.values(cart).reduce((a, b) => a + b, 0);

/** What the customer will pay at the counter: the same GST code the till uses, so
 * the figure on the phone is the figure on the bill. */
export function cartTotal(items: PublicItem[], cart: Cart, gstType: GstType): number {
  const lines = items
    .filter((i) => (cart[i.id] ?? 0) > 0 && !i.sold_out)
    .map((i) => ({
      unitPricePaise: i.price_paise,
      qty: cart[i.id],
      gstRateBp: i.gst_rate_bp,
      taxInclusive: i.tax_inclusive,
    }));
  return lines.length === 0 ? 0 : computeBill(lines, gstType).total;
}

/** Items that were picked and have since sold out (the menu refreshes while they browse). */
export const soldOutInCart = (items: PublicItem[], cart: Cart): string[] =>
  items.filter((i) => i.sold_out && (cart[i.id] ?? 0) > 0).map((i) => i.name);

export function byCategory(items: PublicItem[]): { category: string; items: PublicItem[] }[] {
  const order: string[] = [];
  const groups = new Map<string, PublicItem[]>();
  for (const i of items) {
    if (!groups.has(i.category)) {
      groups.set(i.category, []);
      order.push(i.category);
    }
    groups.get(i.category)!.push(i);
  }
  return order.map((category) => ({ category, items: groups.get(category)! }));
}

/** A mobile number as people type it: spaces, +91 or 0 in front. Null when it is not 10 digits. */
export function cleanPhone(raw: string): string | null {
  let digits = raw.replace(/\D/g, '');
  if (digits.length === 12 && digits.startsWith('91')) digits = digits.slice(2);
  if (digits.length === 11 && digits.startsWith('0')) digits = digits.slice(1);
  return /^[6-9]\d{9}$/.test(digits) ? digits : null;
}

export type OrderStatus = 'received' | 'ready' | 'collected' | 'declined';

export const STATUS_TEXT: Record<OrderStatus, { title: string; detail: string }> = {
  received: { title: 'Order received', detail: 'The outlet has it and will start on it.' },
  ready: { title: 'Ready to collect', detail: 'Show your token at the counter and pay there.' },
  collected: { title: 'Collected', detail: 'Enjoy! Thank you.' },
  declined: { title: 'Sorry, the outlet could not make this', detail: 'Please ask at the counter or order again.' },
};

/** 0..3 steps filled, for the progress bar. */
export const statusStep = (s: OrderStatus): number => (s === 'received' ? 1 : s === 'ready' ? 2 : s === 'collected' ? 3 : 0);

/** The court's page, with the order's key when the customer is following one. */
export const courtPath = (slug: string): string => `/order/${encodeURIComponent(slug)}`;

/** Which food court a path belongs to, or null for the staff app. */
export function courtSlugFromPath(pathname: string): string | null {
  const m = /^\/order\/([a-z0-9-]{1,60})\/?$/.exec(pathname);
  return m ? m[1] : null;
}

/** Why an order was refused, in words for a customer. */
export function orderProblem(code: string | undefined, names?: string[]): string {
  switch (code) {
    case 'outlet_closed':
      return 'This outlet is not taking orders right now.';
    case 'items_unavailable':
      return names?.length ? `Sold out: ${names.join(', ')}. Please remove it and try again.` : 'Some dishes are no longer available.';
    case 'too_many_orders':
      return 'Too many orders from this number. Please try again a little later.';
    case 'outlet_busy':
      return 'This outlet is very busy right now. Please try again shortly.';
    case 'order_too_big':
      return 'That is a lot for one order. Please split it into two.';
    default:
      return 'Could not place the order. Please try again.';
  }
}

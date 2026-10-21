/** The customer's side of a food court order: pure helpers, tested in foodcourt.test.ts. */
import { computeBill, type GstType } from './gst';
import { dishName, t } from './i18n';

/** An option a dish offers (Large, less sugar). `is_size` options change how much is made, so a
 * customer picks one of them at most; the rest are tick boxes. */
export interface PublicOption {
  id: string;
  name: string;
  price_delta_paise: number;
  is_size: boolean;
}

export interface PublicItem {
  id: string;
  name: string;
  name_ta?: string;
  category: string;
  price_paise: number;
  gst_rate_bp: number;
  tax_inclusive: boolean;
  sold_out: boolean;
  description: string;
  description_ta?: string;
  photo_url: string;
  is_veg: boolean;
  options: PublicOption[];
}

/** One line in the cart: a dish with the options ticked on it. Two teas, and one Large tea, are
 * two lines. */
export interface CartLine {
  itemId: string;
  qty: number;
  mods: string[]; // option ids, sorted so the same choice is always the same line
}

/** line key -> the line */
export type Cart = Record<string, CartLine>;

export const MAX_QTY = 20;

export const lineKey = (itemId: string, mods: string[]): string => [itemId, ...[...mods].sort()].join('|');

export function changeLine(cart: Cart, itemId: string, mods: string[], delta: number): Cart {
  const sorted = [...mods].sort();
  const key = lineKey(itemId, sorted);
  const next = Math.max(0, Math.min(MAX_QTY, (cart[key]?.qty ?? 0) + delta));
  const { [key]: _gone, ...rest } = cart;
  return next === 0 ? rest : { ...rest, [key]: { itemId, qty: next, mods: sorted } };
}

/** One cart per outlet, together: a customer can take dishes from several outlets of a
 * court and place them all at once (one order, and one token, per outlet). */
export type Carts = Record<string, Cart>;

export function changeOutletLine(carts: Carts, outletId: string, itemId: string, mods: string[], delta: number): Carts {
  const next = changeLine(carts[outletId] ?? {}, itemId, mods, delta);
  const { [outletId]: _gone, ...rest } = carts;
  return Object.keys(next).length === 0 ? rest : { ...rest, [outletId]: next };
}

export const cartCount = (cart: Cart): number => Object.values(cart).reduce((a, l) => a + l.qty, 0);

/** Outlets that have something in the cart, in the order they were first picked. */
export const outletsInCart = (carts: Carts): string[] => Object.keys(carts).filter((id) => cartCount(carts[id]) > 0);

export const allItemCount = (carts: Carts): number => Object.values(carts).reduce((n, c) => n + cartCount(c), 0);

/** How many of a dish are in a cart, whatever options they have. */
export const dishCount = (cart: Cart, itemId: string): number =>
  Object.values(cart).reduce((n, l) => (l.itemId === itemId ? n + l.qty : n), 0);

/** The options of a line that the dish really offers (an option switched off since is skipped). */
const chosen = (item: PublicItem, line: CartLine): PublicOption[] =>
  line.mods.map((id) => item.options.find((o) => o.id === id)).filter((o): o is PublicOption => o !== undefined);

/** The price of one of this dish with these options, before GST is looked at. */
export const unitPrice = (item: PublicItem, mods: string[]): number =>
  item.price_paise + mods.reduce((sum, id) => sum + (item.options.find((o) => o.id === id)?.price_delta_paise ?? 0), 0);

/** "Masala tea (Large, Less sugar)": the same words the server and the outlet use. */
export function lineLabel(item: PublicItem, mods: string[]): string {
  const names = mods
    .map((id) => item.options.find((o) => o.id === id)?.name)
    .filter((n): n is string => n !== undefined)
    .sort()
    .map((n) => t(n));
  return names.length ? `${dishName(item)} (${names.join(', ')})` : dishName(item);
}

/** What the customer will pay: the same GST code the till uses, with each option's price change,
 * so the figure on the phone is the figure on the bill. */
export function cartTotal(items: PublicItem[], cart: Cart, gstType: GstType): number {
  const lines = Object.values(cart).flatMap((line) => {
    const item = items.find((i) => i.id === line.itemId);
    if (!item || item.sold_out || line.qty <= 0) return [];
    return [
      {
        unitPricePaise: item.price_paise,
        qty: line.qty,
        gstRateBp: item.gst_rate_bp,
        taxInclusive: item.tax_inclusive,
        modifierDeltasPaise: chosen(item, line).map((o) => o.price_delta_paise),
      },
    ];
  });
  return lines.length === 0 ? 0 : computeBill(lines, gstType).total;
}

/** The whole cart at the counters: each outlet's total, worked out the way that outlet's bill will be. */
export function grandTotal(menus: Record<string, { items: PublicItem[]; gst_type: GstType }>, carts: Carts): number {
  return outletsInCart(carts).reduce((sum, id) => (menus[id] ? sum + cartTotal(menus[id].items, carts[id], menus[id].gst_type) : sum), 0);
}

/** Items that were picked and have since sold out (the menu refreshes while they browse). */
export const soldOutInCart = (items: PublicItem[], cart: Cart): string[] => {
  const names = new Set<string>();
  for (const line of Object.values(cart)) {
    const item = items.find((i) => i.id === line.itemId);
    if (item?.sold_out) names.add(item.name);
  }
  return [...names];
};

/** Take out the lines the menu no longer has (a dish gone, or an option switched off), as happens
 * when "order again" meets a changed menu. Returns what is left and how many lines were dropped. */
export function pruneCart(items: PublicItem[], cart: Cart): { cart: Cart; dropped: number } {
  const kept: Cart = {};
  let dropped = 0;
  for (const [key, line] of Object.entries(cart)) {
    const item = items.find((i) => i.id === line.itemId);
    const offered = item !== undefined && line.mods.every((id) => item.options.some((o) => o.id === id));
    if (offered) kept[key] = line;
    else dropped += 1;
  }
  return { cart: kept, dropped };
}

/** An old order's lines (from My orders) as a cart: dish ids, quantities and option ids. */
export function cartFromLines(lines: { menu_item_id: string; qty: number; modifier_ids: string[] }[]): Cart {
  let cart: Cart = {};
  for (const l of lines) cart = changeLine(cart, l.menu_item_id, l.modifier_ids, Math.min(l.qty, MAX_QTY));
  return cart;
}

/** The items of an order or checkout request, as the server takes them. */
export const cartItems = (cart: Cart): { menu_item_id: string; qty: number; modifier_ids: string[] }[] =>
  Object.values(cart).map((l) => ({ menu_item_id: l.itemId, qty: l.qty, modifier_ids: l.mods }));

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

export type PayChoice = 'online' | 'counter';

/** What the customer is told about an outlet that could not take its part of a paid cart. */
export function notPlacedText(o: { outlet: string; error: string | null; message: string | null; refunded: boolean | null; amount_paise: number }, rupees: string): string {
  const why =
    o.error === 'price_changed' ? t('a price changed while you were paying') : (o.message ?? t('it could not take the order')).replace(/\.$/, '');
  return o.refunded === false
    ? t('{outlet}: {why}. We could not refund {rupees} automatically; the food court team will do it.', { outlet: o.outlet, why, rupees })
    : t('{outlet}: {why}. {rupees} is being refunded to your UPI or card. It can take 5 to 7 working days.', { outlet: o.outlet, why, rupees });
}

/** The customer area's front door: /order, with no court chosen yet. */
export const isOrderHome = (pathname: string): boolean => /^\/order\/?$/.test(pathname);

export const ORDER_HOME = '/order';

/** Case-insensitive match on a court's name or place, for the picker's search box. */
export function courtMatches(c: { name: string; location: string }, query: string): boolean {
  const q = query.trim().toLowerCase();
  return q === '' || `${c.name} ${c.location}`.toLowerCase().includes(q);
}

/** What went wrong with sign-up, log-in or a password change, in words for a customer. */
export function accountProblem(status: number, code?: string, serverMessage?: string): string {
  if (status === 429 && serverMessage) return serverMessage;
  switch (code) {
    case 'phone_taken':
      return t('This number already has an account. Log in instead.');
    case 'weak_password':
      return serverMessage || t('Choose a stronger password.');
    case 'wrong_password':
      return t('Your current password is not right.');
    case 'name_required':
      return t('Enter your name.');
  }
  if (status === 401) return t('Phone number or password is wrong.');
  if (status === 422) return t('Check your name, a 10-digit mobile number and a password.');
  return t('Could not do that. Please try again.');
}

/** Why an order was refused, in words for a customer. */
export function orderProblem(code: string | undefined, names?: string[]): string {
  switch (code) {
    case 'outlet_closed':
      return t('This outlet is not taking orders right now.');
    case 'items_unavailable':
      return names?.length ? t('Sold out: {names}. Please remove it and try again.', { names: names.join(', ') }) : t('Some dishes are no longer available.');
    case 'too_many_orders':
      return t('Too many orders from this number. Please try again a little later.');
    case 'outlet_busy':
      return t('This outlet is very busy right now. Please try again shortly.');
    case 'order_too_big':
      return t('That is a lot for one order. Please split it into two.');
    default:
      return t('Could not place the order. Please try again.');
  }
}

/** "840" or "840.50" typed in rupees -> paise, with no floating point. Null when it is not a
 * positive amount with at most two decimals. */
export function rupeesToPaise(text: string): number | null {
  const m = /^(\d{1,7})(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!m) return null;
  const paise = Number(m[1]) * 100 + Number((m[2] ?? '').padEnd(2, '0'));
  return paise > 0 ? paise : null;
}

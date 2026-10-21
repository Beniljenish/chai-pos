import { describe, expect, it } from 'vitest';
import {
  accountProblem,
  allItemCount,
  byCategory,
  cartCount,
  cartFromLines,
  cartItems,
  cartTotal,
  changeLine,
  changeOutletLine,
  cleanPhone,
  courtMatches,
  courtSlugFromPath,
  dishCount,
  grandTotal,
  isOrderHome,
  lineKey,
  lineLabel,
  notPlacedText,
  outletsInCart,
  pruneCart,
  rupeesToPaise,
  orderProblem,
  soldOutInCart,
  statusStep,
  unitPrice,
  type Cart,
  type PublicItem,
} from './foodcourt';

const item = (id: string, name: string, price: number, extra: Partial<PublicItem> = {}): PublicItem => ({
  id,
  name,
  category: 'Tea',
  price_paise: price,
  gst_rate_bp: 500,
  tax_inclusive: true,
  sold_out: false,
  description: '',
  photo_url: '',
  is_veg: true,
  options: [],
  ...extra,
});

// A cart written the short way for tests: [dish id, qty, option ids]
const cartOf = (...rows: [string, number, string[]?][]): Cart =>
  rows.reduce((c, [id, qty, mods]) => changeLine(c, id, mods ?? [], qty), {} as Cart);
const tea = item('t', 'Masala tea', 2000);
const juice = item('j', 'Orange juice', 6000, { category: 'Juice' });

describe('changeLine', () => {
  it('adds and removes, and a zero leaves the cart', () => {
    let c = changeLine({}, 't', [], 1);
    c = changeLine(c, 't', [], 1);
    expect(c).toEqual({ t: { itemId: 't', qty: 2, mods: [] } });
    expect(changeLine(changeLine(c, 't', [], -1), 't', [], -1)).toEqual({});
  });
  it('never goes below zero or above 20', () => {
    expect(changeLine({}, 't', [], -1)).toEqual({});
    expect(changeLine(cartOf(['t', 20]), 't', [], 1)).toEqual(cartOf(['t', 20]));
  });
  it('makes a tea with options a different line from a plain tea, whatever order they were ticked in', () => {
    const c = cartOf(['t', 1], ['t', 2, ['b', 'a']], ['t', 1, ['a', 'b']]);
    expect(Object.keys(c).sort()).toEqual(['t', 't|a|b']);
    expect(c['t|a|b'].qty).toBe(3);
    expect(lineKey('t', ['b', 'a'])).toBe('t|a|b');
    expect(dishCount(c, 't')).toBe(4);
  });
});

describe('options', () => {
  const large = { id: 'L', name: 'Large', price_delta_paise: 1000, is_size: true };
  const less = { id: 'S', name: 'Less sugar', price_delta_paise: 0, is_size: false };
  const masala = { ...tea, options: [large, less] };

  it('prices an option into the total, the way the server does', () => {
    // 2 x (₹20 + ₹10 Large) = ₹60, GST included, to the rupee: the number the backend test pins
    expect(cartTotal([masala], cartOf(['t', 2, ['L', 'S']]), 'regular')).toBe(6000);
    expect(cartTotal([masala], cartOf(['t', 1], ['t', 1, ['L']]), 'regular')).toBe(5000);
    expect(unitPrice(masala, ['L', 'S'])).toBe(3000);
  });

  it('ignores an option the dish no longer offers instead of guessing', () => {
    expect(cartTotal([masala], cartOf(['t', 1, ['gone']]), 'regular')).toBe(2000);
  });

  it('labels a line like the server and the outlet do, options in alphabetical order', () => {
    expect(lineLabel(masala, ['S', 'L'])).toBe('Masala tea (Large, Less sugar)');
    expect(lineLabel(masala, [])).toBe('Masala tea');
  });

  it('drops lines whose dish or option is gone, and says how many', () => {
    const cart = cartOf(['t', 1], ['t', 1, ['L']], ['j', 1], ['t', 1, ['gone']]);
    const { cart: kept, dropped } = pruneCart([masala], cart);
    expect(dropped).toBe(2);
    expect(Object.keys(kept).sort()).toEqual(['t', 't|L']);
  });

  it('turns an old order back into a cart, and a cart into what the server takes', () => {
    const cart = cartFromLines([
      { menu_item_id: 't', qty: 2, modifier_ids: ['L', 'S'] },
      { menu_item_id: 'j', qty: 1, modifier_ids: [] },
    ]);
    expect(cartCount(cart)).toBe(3);
    expect(cartItems(cart).sort((a, b) => a.menu_item_id.localeCompare(b.menu_item_id))).toEqual([
      { menu_item_id: 'j', qty: 1, modifier_ids: [] },
      { menu_item_id: 't', qty: 2, modifier_ids: ['L', 'S'] },
    ]);
    // more than the limit in an old order is clamped, never sent
    expect(cartCount(cartFromLines([{ menu_item_id: 't', qty: 99, modifier_ids: [] }]))).toBe(20);
  });
});

describe('cartTotal', () => {
  it('is the till total: 2 teas and a juice, GST included, to the rupee', () => {
    const cart = cartOf(['t', 2], ['j', 1]);
    expect(cartTotal([tea, juice], cart, 'regular')).toBe(10000);
    expect(cartCount(cart)).toBe(3);
  });
  it('is zero for an empty cart and ignores sold-out dishes', () => {
    expect(cartTotal([tea], {}, 'regular')).toBe(0);
    expect(cartTotal([{ ...tea, sold_out: true }], cartOf(['t', 2]), 'regular')).toBe(0);
  });
  it('adds GST on top for a price that excludes it', () => {
    const plus = item('p', 'Plus', 10000, { tax_inclusive: false });
    expect(cartTotal([plus], cartOf(['p', 1]), 'regular')).toBe(10500);
    expect(cartTotal([plus], cartOf(['p', 1]), 'unregistered')).toBe(10000);
  });
});

describe('soldOutInCart', () => {
  it('names dishes that sold out after they were picked', () => {
    expect(soldOutInCart([{ ...tea, sold_out: true }, juice], cartOf(['t', 1], ['j', 1]))).toEqual(['Masala tea']);
  });
});

describe('byCategory', () => {
  it('keeps the menu order', () => {
    expect(byCategory([tea, juice, item('l', 'Lemon tea', 1500)]).map((g) => [g.category, g.items.length])).toEqual([
      ['Tea', 2],
      ['Juice', 1],
    ]);
  });
});

describe('cleanPhone', () => {
  it('accepts the ways people type a mobile number', () => {
    for (const raw of ['98400 12345', '+91 98400-12345', '09840012345', '9840012345']) {
      expect(cleanPhone(raw)).toBe('9840012345');
    }
  });
  it('refuses anything else', () => {
    for (const raw of ['', '12345', '5840012345', '98400123456']) expect(cleanPhone(raw)).toBeNull();
  });
});

describe('courtSlugFromPath', () => {
  it('finds a court, and nothing for the staff app', () => {
    expect(courtSlugFromPath('/order/marina-food-court-3f9a')).toBe('marina-food-court-3f9a');
    expect(courtSlugFromPath('/order/marina-food-court-3f9a/')).toBe('marina-food-court-3f9a');
    for (const p of ['/', '/order', '/order/', '/order/a/b', '/order/Bad_Slug', '/orders/x']) {
      expect(courtSlugFromPath(p)).toBeNull();
    }
  });
});

describe('words for the customer', () => {
  it('says why an order was refused', () => {
    expect(orderProblem('items_unavailable', ['Masala tea'])).toBe('Sold out: Masala tea. Please remove it and try again.');
    expect(orderProblem('outlet_closed')).toContain('not taking orders');
    expect(orderProblem(undefined)).toBe('Could not place the order. Please try again.');
  });
  it('fills the progress bar', () => {
    expect(['received', 'ready', 'collected', 'declined'].map((s) => statusStep(s as never))).toEqual([1, 2, 3, 0]);
  });
});

describe('one cart across outlets', () => {
  const juice = item('j', 'Orange juice', 6000, { gst_rate_bp: 0 });
  const menus = {
    a: { items: [tea], gst_type: 'regular' as const },
    b: { items: [juice], gst_type: 'regular' as const },
  };

  it('keeps a cart per outlet and drops an outlet when its cart empties', () => {
    let carts = changeOutletLine({}, 'a', 't', [], 2);
    carts = changeOutletLine(carts, 'b', 'j', [], 1);
    expect(outletsInCart(carts)).toEqual(['a', 'b']);
    expect(allItemCount(carts)).toBe(3);
    carts = changeOutletLine(carts, 'a', 't', [], -2);
    expect(outletsInCart(carts)).toEqual(['b']);
    expect(carts).toEqual({ b: { j: { itemId: 'j', qty: 1, mods: [] } } });
  });

  it('adds each outlet total the way that outlet bills it', () => {
    const carts = { a: cartOf(['t', 2]), b: cartOf(['j', 1]) };
    expect(grandTotal(menus, carts)).toBe(cartTotal(menus.a.items, carts.a, 'regular') + cartTotal(menus.b.items, carts.b, 'regular'));
    // an outlet whose menu has not loaded yet adds nothing instead of guessing
    expect(grandTotal({ a: menus.a }, carts)).toBe(cartTotal(menus.a.items, carts.a, 'regular'));
  });
});

describe('the customer front door', () => {
  it('knows /order from a court page', () => {
    expect(isOrderHome('/order')).toBe(true);
    expect(isOrderHome('/order/')).toBe(true);
    expect(isOrderHome('/order/marina-1a2b')).toBe(false);
    expect(isOrderHome('/')).toBe(false);
    expect(courtSlugFromPath('/order')).toBeNull();
  });

  it('searches courts by name or place', () => {
    const c = { name: 'Marina Food Court', location: 'Marina Beach, Chennai' };
    expect(courtMatches(c, '')).toBe(true);
    expect(courtMatches(c, 'chennai')).toBe(true);
    expect(courtMatches(c, '  MARINA ')).toBe(true);
    expect(courtMatches(c, 'adyar')).toBe(false);
  });

  it('explains account problems in words', () => {
    expect(accountProblem(409, 'phone_taken')).toMatch(/already has an account/);
    expect(accountProblem(401)).toMatch(/wrong/);
    expect(accountProblem(429, undefined, 'Too many wrong passwords. Try again in 15 minutes.')).toMatch(/15 minutes/);
    expect(accountProblem(422, 'weak_password', 'Use at least 8 characters')).toBe('Use at least 8 characters');
  });
});

describe('paying online', () => {
  it('turns typed rupees into paise without floating point', () => {
    expect(rupeesToPaise('840')).toBe(84000);
    expect(rupeesToPaise(' 840.5 ')).toBe(84050);
    expect(rupeesToPaise('0.07')).toBe(7);
    expect(rupeesToPaise('1234567.99')).toBe(123456799);
    for (const bad of ['', '0', '0.00', '-5', '1.234', 'abc', '1,000', '12345678']) expect(rupeesToPaise(bad)).toBeNull();
  });

  it('tells the customer what became of an outlet that could not take its part', () => {
    const part = { outlet: 'Anna Biryani', error: 'items_unavailable', message: 'Sold out: Biryani.', refunded: true, amount_paise: 18000 };
    expect(notPlacedText(part, '₹180')).toBe(
      'Anna Biryani: Sold out: Biryani. ₹180 is being refunded to your UPI or card. It can take 5 to 7 working days.',
    );
    expect(notPlacedText({ ...part, error: 'price_changed', message: 'x' }, '₹180')).toMatch(/a price changed while you were paying/);
    // a refund that failed is never promised
    expect(notPlacedText({ ...part, refunded: false }, '₹180')).toMatch(/could not refund ₹180 automatically/);
  });
});

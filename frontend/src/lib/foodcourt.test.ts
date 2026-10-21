import { describe, expect, it } from 'vitest';
import {
  accountProblem,
  allItemCount,
  byCategory,
  cartCount,
  cartTotal,
  changeOutletQty,
  changeQty,
  cleanPhone,
  courtMatches,
  courtSlugFromPath,
  grandTotal,
  isOrderHome,
  outletsInCart,
  orderProblem,
  soldOutInCart,
  statusStep,
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
  ...extra,
});
const tea = item('t', 'Masala tea', 2000);
const juice = item('j', 'Orange juice', 6000, { category: 'Juice' });

describe('changeQty', () => {
  it('adds and removes, and a zero leaves the cart', () => {
    let c = changeQty({}, 't', 1);
    c = changeQty(c, 't', 1);
    expect(c).toEqual({ t: 2 });
    expect(changeQty(changeQty(c, 't', -1), 't', -1)).toEqual({});
  });
  it('never goes below zero or above 20', () => {
    expect(changeQty({}, 't', -1)).toEqual({});
    expect(changeQty({ t: 20 }, 't', 1)).toEqual({ t: 20 });
  });
});

describe('cartTotal', () => {
  it('is the till total: 2 teas and a juice, GST included, to the rupee', () => {
    expect(cartTotal([tea, juice], { t: 2, j: 1 }, 'regular')).toBe(10000);
    expect(cartCount({ t: 2, j: 1 })).toBe(3);
  });
  it('is zero for an empty cart and ignores sold-out dishes', () => {
    expect(cartTotal([tea], {}, 'regular')).toBe(0);
    expect(cartTotal([{ ...tea, sold_out: true }], { t: 2 }, 'regular')).toBe(0);
  });
  it('adds GST on top for a price that excludes it', () => {
    const plus = item('p', 'Plus', 10000, { tax_inclusive: false });
    expect(cartTotal([plus], { p: 1 }, 'regular')).toBe(10500);
    expect(cartTotal([plus], { p: 1 }, 'unregistered')).toBe(10000);
  });
});

describe('soldOutInCart', () => {
  it('names dishes that sold out after they were picked', () => {
    expect(soldOutInCart([{ ...tea, sold_out: true }, juice], { t: 1, j: 1 })).toEqual(['Masala tea']);
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
    let carts = changeOutletQty({}, 'a', 't', 2);
    carts = changeOutletQty(carts, 'b', 'j', 1);
    expect(outletsInCart(carts)).toEqual(['a', 'b']);
    expect(allItemCount(carts)).toBe(3);
    carts = changeOutletQty(carts, 'a', 't', -2);
    expect(outletsInCart(carts)).toEqual(['b']);
    expect(carts).toEqual({ b: { j: 1 } });
  });

  it('adds each outlet total the way that outlet bills it', () => {
    const carts = { a: { t: 2 }, b: { j: 1 } };
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

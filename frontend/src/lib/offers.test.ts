import { describe, expect, it } from 'vitest';
import { cleanCode, offerState, offerText, type Offer } from './offers';

const base: Offer = {
  id: '1',
  code: 'SAVE10',
  kind: 'percent',
  value: 10,
  min_order_paise: 0,
  max_discount_paise: null,
  valid_until: null,
  max_uses: null,
  is_active: true,
  uses: 0,
};

describe('offers', () => {
  it('say what they take off', () => {
    expect(offerText(base)).toBe('10% off');
    expect(offerText({ ...base, max_discount_paise: 2000, min_order_paise: 10000 })).toBe('10% off (up to ₹20) · on orders of ₹100 or more');
    expect(offerText({ ...base, kind: 'amount', value: 5000 })).toBe('₹50 off');
  });

  it('say why one does not work', () => {
    expect(offerState(base, '2026-10-22')).toBe('on');
    expect(offerState({ ...base, is_active: false }, '2026-10-22')).toBe('off');
    expect(offerState({ ...base, valid_until: '2026-10-21' }, '2026-10-22')).toBe('expired');
    expect(offerState({ ...base, valid_until: '2026-10-22' }, '2026-10-22')).toBe('on'); // the last day counts
    expect(offerState({ ...base, max_uses: 5, uses: 5 }, '2026-10-22')).toBe('used_up');
  });

  it('clean a typed code the way the server does', () => {
    expect(cleanCode(' save 10 ')).toBe('SAVE10');
    expect(cleanCode('ab')).toBeNull();
    expect(cleanCode('no-dash')).toBeNull();
  });
});

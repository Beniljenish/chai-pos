import { describe, expect, it } from 'vitest';
import { marginTone, sortMargins, whyNoMargin } from './margin';
import type { MarginItem } from './types';

const item = (name: string, pct: number | null, sold = 0, extra: Partial<MarginItem> = {}): MarginItem => ({
  menu_item_id: name,
  name,
  category: 'Tea',
  price_paise: 2000,
  net_paise: 1904,
  sold_28d: sold,
  cost_paise: pct === null ? null : 600,
  margin_paise: pct === null ? null : 1300,
  margin_pct: pct,
  status: pct === null ? 'incomplete' : 'ok',
  missing: [],
  ...extra,
});

describe('marginTone', () => {
  it('is pink under half, amber to two thirds, green above', () => {
    expect(marginTone(49)).toBe('bad');
    expect(marginTone(50)).toBe('near');
    expect(marginTone(66)).toBe('near');
    expect(marginTone(67)).toBe('ok');
  });
  it('has no colour without a margin', () => {
    expect(marginTone(null)).toBe('none');
  });
});

describe('sortMargins', () => {
  const items = [item('Tea', 69, 300), item('Shake', 48, 90), item('Juice', null), item('Coffee', 74, 120)];
  it('worst first, items we cannot cost last', () => {
    expect(sortMargins(items, 'worst').map((i) => i.name)).toEqual(['Shake', 'Tea', 'Coffee', 'Juice']);
  });
  it('best first, still leaving the uncosted last', () => {
    expect(sortMargins(items, 'best').map((i) => i.name)).toEqual(['Coffee', 'Tea', 'Shake', 'Juice']);
  });
  it('by what sold most in 28 days', () => {
    expect(sortMargins(items, 'sales').map((i) => i.name)).toEqual(['Tea', 'Coffee', 'Shake', 'Juice']);
  });
});

describe('whyNoMargin', () => {
  it('names the ingredients with no price', () => {
    expect(whyNoMargin(item('Tea', null, 0, { missing: ['Milk', 'Sugar'] }))).toBe(
      'Add a price for Milk, Sugar (enter it with a stock-in)',
    );
  });
  it('says when there is no recipe', () => {
    expect(whyNoMargin(item('Tea', null, 0, { status: 'no_recipe' }))).toBe('No recipe yet, so the cost is unknown');
  });
});

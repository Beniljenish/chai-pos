import { describe, expect, it } from 'vitest';
import {
  blankOption,
  describeOption,
  formatPriceDelta,
  previewServing,
  toDraft,
  toOptionPayload,
  validateOption,
  type OptionDraft,
} from './options';
import type { Ingredient, Modifier, RecipeLine } from './types';

const ing = (id: string, name: string, base_unit: Ingredient['base_unit'], scales = true): Ingredient => ({
  id,
  name,
  kind: 'raw',
  base_unit,
  scales_with_size: scales,
  is_active: true,
  reorder_level: null,
  pack_units: [],
});
const byId = {
  dec: ing('dec', 'Tea decoction', 'ml'),
  sugar: ing('sugar', 'Sugar', 'g'),
  cup: ing('cup', 'Paper cup', 'piece', false),
};
const recipe: RecipeLine[] = [
  { ingredient_id: 'dec', ingredient_name: 'Tea decoction', base_unit: 'ml', qty: '100.000' },
  { ingredient_id: 'sugar', ingredient_name: 'Sugar', base_unit: 'g', qty: '8.000' },
  { ingredient_id: 'cup', ingredient_name: 'Paper cup', base_unit: 'piece', qty: '1.000' },
];
const large: Modifier = {
  id: 'm',
  name: 'Large',
  price_delta_paise: 1000,
  scale_factor: '1.500',
  is_active: true,
  lines: [{ ingredient_id: 'sugar', qty_delta: '2.000' }],
};

describe('draft round trip', () => {
  it('turns signed amounts into direction + number and back', () => {
    const less: Modifier = { ...large, name: 'Small', price_delta_paise: -500, lines: [{ ingredient_id: 'sugar', qty_delta: '-3.000' }] };
    const d = toDraft(less);
    expect(d.priceDir).toBe('less');
    expect(d.price).toBe('5');
    expect(d.lines[0]).toMatchObject({ dir: 'less', qty: '3' });
    expect(toOptionPayload(d)).toEqual({
      name: 'Small',
      price_delta_paise: -500,
      scale_factor: '1.5',
      lines: [{ ingredient_id: 'sugar', qty_delta: '-3' }],
    });
  });

  it('an empty price means no price change', () => {
    const d: OptionDraft = { ...blankOption(), name: 'Less sugar' };
    expect(toOptionPayload(d).price_delta_paise).toBe(0);
    expect(validateOption(d)).toBeNull();
  });
});

describe('validation', () => {
  const ok: OptionDraft = toDraft(large);
  it.each([
    [{ name: ' ' }, 'name'],
    [{ scale: '0' }, 'Size'],
    [{ scale: '' }, 'Size'],
    [{ price: '101' }, '₹100'],
    [{ lines: [{ key: 'a', ingredient_id: '', dir: 'more' as const, qty: '1' }] }, 'Choose an ingredient'],
    [{ lines: [{ key: 'a', ingredient_id: 'sugar', dir: 'less' as const, qty: '0' }] }, 'more than zero'],
    [
      {
        lines: [
          { key: 'a', ingredient_id: 'sugar', dir: 'less' as const, qty: '1' },
          { key: 'b', ingredient_id: 'sugar', dir: 'more' as const, qty: '1' },
        ],
      },
      'only once',
    ],
  ])('refuses %j', (patch, words) => {
    expect(validateOption({ ...ok, ...patch })).toContain(words);
  });
});

describe('preview matches the server rule', () => {
  it('Large: liquids grow 1.5x, the cup does not, sugar change added after scaling', () => {
    const rows = Object.fromEntries(previewServing(recipe, toDraft(large), byId).map((r) => [r.name, r]));
    expect(rows['Tea decoction']).toMatchObject({ before: 100, after: 150 });
    expect(rows['Sugar']).toMatchObject({ before: 8, after: 14 });
    expect(rows['Paper cup']).toMatchObject({ before: 1, after: 1 });
  });

  it('never goes below zero, and adds ingredients the recipe does not have', () => {
    const d: OptionDraft = {
      ...blankOption(),
      name: 'x',
      lines: [
        { key: 'a', ingredient_id: 'sugar', dir: 'less', qty: '20' },
        { key: 'b', ingredient_id: 'cup', dir: 'more', qty: '1' },
      ],
    };
    const noCup = recipe.filter((l) => l.ingredient_id !== 'cup');
    const rows = Object.fromEntries(previewServing(noCup, d, byId).map((r) => [r.name, r]));
    expect(rows['Sugar'].after).toBe(0);
    expect(rows['Paper cup']).toMatchObject({ before: 0, after: 1 });
  });
});

describe('words', () => {
  it('describes an option in one line', () => {
    expect(describeOption(large, byId)).toBe('+₹10 · 1.5× size · Sugar +2 g');
    expect(describeOption({ ...large, price_delta_paise: 0, scale_factor: '1', lines: [] }, byId)).toBe(
      'No change to price or stock',
    );
  });
  it('price deltas carry a real minus sign', () => {
    expect(formatPriceDelta(-500)).toBe('−₹5');
    expect(formatPriceDelta(1050)).toBe('+₹10.50');
    expect(formatPriceDelta(0)).toBe('');
  });
});

import { describe, expect, it } from 'vitest';
import { fruitGramsPerPortion, toEditable, toPayload, validate } from './recipe';
import type { Recipe } from './types';

const juice: Recipe = {
  id: 'r',
  version: 1,
  effective_from: '2026-10-03T00:00:00Z',
  yield_qty: null,
  yield_inputs: { ingredient_id: 'orange', ml_per_kg: '450', portion_ml: '250', grams_per_portion: '555.556' },
  lines: [
    { ingredient_id: 'cup', ingredient_name: 'Paper cup', base_unit: 'piece', qty: '1.000' },
    { ingredient_id: 'orange', ingredient_name: 'Oranges', base_unit: 'g', qty: '555.556' },
  ],
};

describe('juice yield', () => {
  it('matches the server formula: 250 ml at 450 ml/kg = 555.556 g', () => {
    expect(fruitGramsPerPortion(450, 250)).toBe(555.556);
    expect(fruitGramsPerPortion(0, 250)).toBeNull();
  });
  it('edits the fruit through the yield, not as a plain line', () => {
    const { lines, juice: j } = toEditable(juice);
    expect(lines.map((l) => l.ingredient_id)).toEqual(['cup']);
    expect(j).toEqual({ ingredient_id: 'orange', ml_per_kg: '450', portion_ml: '250' });
    expect(toPayload(lines, j, null)).toEqual({
      lines: [{ ingredient_id: 'cup', qty: '1' }],
      juice_yield: { ingredient_id: 'orange', ml_per_kg: '450', portion_ml: '250' },
    });
  });
});

describe('validate', () => {
  const line = (id: string, qty: string) => ({ key: id + qty, ingredient_id: id, qty });
  it('accepts a normal recipe', () => {
    expect(validate([line('dec', '100'), line('cup', '1')], null, null)).toBeNull();
  });
  it('explains each mistake in plain words', () => {
    expect(validate([], null, null)).toMatch(/at least one/);
    expect(validate([line('', '1')], null, null)).toMatch(/Choose an ingredient/);
    expect(validate([line('a', '1'), line('a', '2')], null, null)).toMatch(/only once/);
    expect(validate([line('a', '0')], null, null)).toMatch(/more than zero/);
    expect(validate([line('a', '1')], null, '0')).toMatch(/one batch makes/);
    expect(validate([line('orange', '1')], { ingredient_id: 'orange', ml_per_kg: '450', portion_ml: '250' }, null)).toMatch(
      /only once/,
    );
  });
});

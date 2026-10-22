import { describe, expect, it } from 'vitest';
import { spiceLabel, withoutAllergens } from './allergens';

describe('allergy tags', () => {
  const items = [
    { name: 'tea', allergens: ['milk'] },
    { name: 'chikki', allergens: ['nuts'] },
    { name: 'water', allergens: [] },
    { name: 'old', allergens: undefined },
  ];
  it('hide every dish with a tag the customer avoids', () => {
    expect(withoutAllergens(items, ['nuts']).map((i) => i.name)).toEqual(['tea', 'water', 'old']);
    expect(withoutAllergens(items, ['nuts', 'milk']).map((i) => i.name)).toEqual(['water', 'old']);
    expect(withoutAllergens(items, [])).toBe(items);
  });
  it('name the spice level, or nothing when it was not said', () => {
    expect(spiceLabel(0)).toBe('Not spicy');
    expect(spiceLabel(3)).toBe('Hot');
    expect(spiceLabel(null)).toBeNull();
    expect(spiceLabel(7)).toBeNull();
  });
});

import { describe, expect, it } from 'vitest';
import { draftTotal, lineReady, showQty, withCost, withIngredient, withQty, type DraftLine } from './aiTypes';

const line = (over: Partial<DraftLine> = {}): DraftLine => ({
  heard_name: 'milk',
  ingredient_id: 'i1',
  ingredient_name: 'Milk',
  base_unit: 'ml',
  base_qty: '20000.000',
  cost_paise: 48000,
  problems: [],
  ...over,
});

describe('a draft line', () => {
  it('is ready only with an item, a quantity and a price', () => {
    expect(lineReady(line())).toBe(true);
    expect(lineReady(line({ ingredient_id: null }))).toBe(false);
    expect(lineReady(line({ base_qty: null }))).toBe(false);
    expect(lineReady(line({ cost_paise: 0 }))).toBe(false);
  });

  it('shows quantities the way a shop says them', () => {
    expect(showQty('ml', '20000.000')).toBe('20 L');
    expect(showQty('g', '2500.000')).toBe('2.5 kg');
    expect(showQty('piece', '12.000')).toBe('12 pcs');
    expect(showQty('ml', null)).toBe('–');
  });

  it('clears the matching problem once the owner fixes it', () => {
    const bad = line({ ingredient_id: null, base_qty: null, cost_paise: 0, problems: ['Pick which stock item this is', 'The quantity was not clear', 'No price was heard: type it'] });
    expect(withIngredient(bad, 'i2', 'Sugar', 'g').problems).toEqual(['The quantity was not clear', 'No price was heard: type it']);
    expect(withQty(bad, '5000').problems).toContain('No price was heard: type it');
    expect(withQty(bad, '5000').base_qty).toBe('5000');
    expect(withQty(bad, 'lots').base_qty).toBeNull();
    expect(withCost(bad, 12000).problems).not.toContain('No price was heard: type it');
  });

  it('adds the lines up in paise', () => {
    expect(draftTotal([line(), line({ cost_paise: 22500 })])).toBe(70500);
  });
});

import { describe, expect, it } from 'vitest';
import { stockLevel, worstFirst } from './stockLevel';

describe('stockLevel', () => {
  it('is bad below the reorder level, with the tick at half', () => {
    expect(stockLevel('3200', '8000')).toEqual({ tone: 'bad', fillPct: 20, tickPct: 50 });
  });
  it('is near up to a quarter above the level, then ok', () => {
    expect(stockLevel('8000', '8000').tone).toBe('near');
    expect(stockLevel('9999', '8000').tone).toBe('near');
    expect(stockLevel('10000', '8000').tone).toBe('ok');
  });
  it('caps the bar at full', () => {
    expect(stockLevel('99999', '8000').fillPct).toBe(100);
  });
  it('draws an empty bad bar for negative stock', () => {
    expect(stockLevel('-300', '8000')).toEqual({ tone: 'bad', fillPct: 0, tickPct: 50 });
  });
  it('has no bar without a reorder level', () => {
    expect(stockLevel('500', null)).toEqual({ tone: 'none', fillPct: 0, tickPct: null });
    expect(stockLevel('500', '0').tone).toBe('none');
  });
});

describe('worstFirst', () => {
  it('orders bad, near, ok, none, then emptiest, then name', () => {
    const row = (name: string, on: string, re: string | null) => ({ name, level: stockLevel(on, re) });
    const out = worstFirst([
      row('Cups', '1000', '300'),
      row('Water', '5', null),
      row('Tea', '900', '2000'),
      row('Milk', '3200', '8000'),
      row('Sugar', '5200', '5000'),
    ]);
    expect(out.map((r) => r.name)).toEqual(['Milk', 'Tea', 'Sugar', 'Cups', 'Water']);
  });
});

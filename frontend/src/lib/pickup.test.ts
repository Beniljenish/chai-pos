import { describe, expect, it } from 'vitest';
import { slotLabel, tableFromSearch, tableLink } from './pickup';

describe('pickup helpers', () => {
  it('shows a slot on an Indian clock', () => {
    expect(slotLabel('2026-10-22T07:15:00Z')).toBe('12:45 pm');
    expect(slotLabel('2026-10-22T18:30:00Z')).toBe('12:00 am');
  });

  it('reads the table and outlet from a table QR link', () => {
    const id = '0f8fad5b-d9cb-469f-a165-70867728950e';
    expect(tableFromSearch(`?outlet=${id}&table=Table%204`)).toEqual({ outlet: id, table: 'Table 4' });
    expect(tableFromSearch('?outlet=nonsense&table=%20T1%20')).toEqual({ outlet: null, table: 'T1' });
    expect(tableFromSearch('')).toEqual({ outlet: null, table: '' });
    expect(tableFromSearch('?table=' + 'x'.repeat(40)).table).toHaveLength(20);
  });

  it('builds the link a table QR carries, and it reads back', () => {
    const id = '0f8fad5b-d9cb-469f-a165-70867728950e';
    const url = new URL(tableLink('https://app.example', 'marina', id, 'Table 4'));
    expect(url.pathname).toBe('/order/marina');
    expect(tableFromSearch(url.search)).toEqual({ outlet: id, table: 'Table 4' });
  });
});

import { describe, expect, it } from 'vitest';
import { NO_ATTENTION, attentionTotal, badgesFor } from './attention';

describe('attention', () => {
  it('shows no badge when all is fine', () => {
    expect(badgesFor(NO_ATTENTION)).toEqual({});
    expect(attentionTotal(NO_ATTENTION)).toBe(0);
  });
  it('words each badge and colours it by urgency', () => {
    const a = { lowStock: 4, toApprove: 1, owing: 3 };
    expect(badgesFor(a)).toEqual({
      stock: { text: '4 low', urgency: 'act' },
      dayend: { text: '1 to approve', urgency: 'act' },
      khata: { text: '3 owe', urgency: 'look' },
    });
    expect(attentionTotal(a)).toBe(8);
  });
  it('says "owes" for one customer', () => {
    expect(badgesFor({ lowStock: 0, toApprove: 0, owing: 1 }).khata?.text).toBe('1 owes');
  });
});

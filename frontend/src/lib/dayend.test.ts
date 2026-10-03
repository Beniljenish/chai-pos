import { describe, expect, it } from 'vitest';
import { adherenceWords, countableDays, mustCount } from './dayend';

describe('day end helpers', () => {
  it('offers today and yesterday in shop time', () => {
    // 00:30 IST on 4 Oct is still 3 Oct 19:00 UTC: "today" is 4 Oct in the shop.
    const days = countableDays(new Date('2026-10-03T19:00:00Z'));
    expect(days.map((d) => d.date)).toEqual(['2026-10-04', '2026-10-03']);
    expect(days[1].label).toBe('Yesterday, 3 Oct');
  });
  it('requires daily and shift items, not weekly ones', () => {
    expect(mustCount('daily')).toBe(true);
    expect(mustCount('shift')).toBe(true);
    expect(mustCount('weekly')).toBe(false);
  });
  it('turns adherence into words, from actual usage', () => {
    // 88.9% adherence: actual usage = expected / 0.889, i.e. 100/88.9 - 1 = 12.49% more
    expect(adherenceWords('88.9')).toBe('Used 12% more than the recipe');
    expect(adherenceWords('100.0')).toBe('Matches the recipe');
    expect(adherenceWords('105.0')).toBe('Used 5% less than the recipe');
    expect(adherenceWords(null)).toBeNull();
  });
});

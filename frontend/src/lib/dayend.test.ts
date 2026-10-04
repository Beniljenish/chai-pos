import { describe, expect, it } from 'vitest';
import { adherenceWords, countableDays, mustCount, sparkPoints, sparkY100, trendVerdict } from './dayend';

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

describe('adherence trend', () => {
  it('tells a recipe problem from a people problem', () => {
    expect(trendVerdict(['88.9', '90.1'])).toBe('few'); // two days prove nothing
    expect(trendVerdict(['99.0', '101.5', '100.2', null])).toBe('on');
    // every day ~10% over the recipe: the recipe is wrong
    expect(trendVerdict(['89.0', '90.5', '88.2', '91.0'])).toBe('steady');
    // fine most days, bad on some: look at the shift
    expect(trendVerdict(['99.0', '100.0', '84.0', '98.5'])).toBe('varies');
    expect(trendVerdict([null, null, null])).toBe('few');
  });

  it('places points on a fixed 70-130% scale, one slot per closed day', () => {
    const days = ['2026-10-01', '2026-10-02', '2026-10-03'];
    const pts = sparkPoints(
      days,
      [
        { business_date: '2026-10-01', adherence_pct: '100.0' },
        { business_date: '2026-10-03', adherence_pct: '40.0' }, // clamped to the bottom
      ],
      100,
      30,
    );
    expect(pts).toEqual([
      { x: 0, y: 15, date: '2026-10-01', pct: 100 },
      { x: 100, y: 30, date: '2026-10-03', pct: 40 },
    ]);
    expect(sparkY100(30)).toBe(15);
    // a single closed day sits in the middle
    expect(sparkPoints(['2026-10-01'], [{ business_date: '2026-10-01', adherence_pct: '130.0' }], 100, 30)).toEqual([
      { x: 50, y: 0, date: '2026-10-01', pct: 130 },
    ]);
  });
});

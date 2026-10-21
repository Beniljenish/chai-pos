import { describe, expect, it } from 'vitest';
import { change, changeText, weekPairs } from './compare';
import { shiftDay } from './sales';

describe('change', () => {
  it('is the whole percent up or down', () => {
    expect(change(14820, 13230)).toEqual({ pct: 12, direction: 'up' });
    expect(change(97, 100)).toEqual({ pct: -3, direction: 'down' });
    expect(change(100, 100)).toEqual({ pct: 0, direction: 'same' });
  });
  it('has no percentage when last week was empty', () => {
    expect(change(500, 0)).toEqual({ pct: null, direction: 'up' });
    expect(change(0, 0)).toEqual({ pct: null, direction: 'none' });
  });
  it('is written with an arrow', () => {
    expect(changeText(change(112, 100))).toBe('▲ 12%');
    expect(changeText(change(90, 100))).toBe('▼ 10%');
    expect(changeText(change(0, 0))).toBe('');
    expect(changeText(change(5, 0))).toBe('new');
  });
});

describe('weekPairs', () => {
  it('pairs each of the last 7 days with the same weekday a week earlier', () => {
    const days = [
      { business_date: '2026-10-06', bills: 3, total_paise: 100 },
      { business_date: '2026-09-29', bills: 2, total_paise: 80 },
      { business_date: '2026-10-05', bills: 1, total_paise: 50 },
    ];
    const pairs = weekPairs(days, '2026-10-06', shiftDay);
    expect(pairs).toHaveLength(7);
    expect(pairs[6]).toEqual({ date: '2026-10-06', now: 100, before: 80 });
    expect(pairs[5]).toEqual({ date: '2026-10-05', now: 50, before: 0 });
    expect(pairs[0].date).toBe('2026-09-30');
  });
});

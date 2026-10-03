import { describe, expect, it } from 'vitest';
import { dayLabel, hourBars, hourLabel, shiftDay, voidReasonLabel } from './sales';

describe('days', () => {
  it('shifts across month and year ends', () => {
    expect(shiftDay('2026-10-01', -1)).toBe('2026-09-30');
    expect(shiftDay('2026-12-31', 1)).toBe('2027-01-01');
    expect(shiftDay('2028-02-28', 1)).toBe('2028-02-29');
  });
  it('labels today, yesterday, and older days by name', () => {
    expect(dayLabel('2026-10-03', '2026-10-03')).toBe('Today');
    expect(dayLabel('2026-10-02', '2026-10-03')).toBe('Yesterday');
    expect(dayLabel('2026-10-01', '2026-10-03')).toBe('Thu, 1 Oct');
  });
});

describe('hours', () => {
  it('reads like a clock', () => {
    expect([0, 7, 12, 19].map(hourLabel)).toEqual(['12 am', '7 am', '12 pm', '7 pm']);
  });
  it('fills quiet hours with zero and scales to the busiest hour', () => {
    const bars = hourBars([
      { hour: 7, bills: 4, total_paise: 8000 },
      { hour: 9, bills: 2, total_paise: 2000 },
    ]);
    expect(bars.map((b) => [b.hour, b.pct])).toEqual([
      [7, 100],
      [8, 0],
      [9, 25],
    ]);
    expect(hourBars([])).toEqual([]);
  });
});

it('names void reasons in plain words', () => {
  expect(voidReasonLabel('payment_failed')).toBe('Payment failed');
  expect(voidReasonLabel('mystery')).toBe('mystery');
});

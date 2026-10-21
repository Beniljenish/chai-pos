/** "vs last week" on Sales: pure helpers, tested in compare.test.ts. */

export interface Change {
  /** Whole percent, positive = up. Null when last week had nothing to compare with. */
  pct: number | null;
  direction: 'up' | 'down' | 'same' | 'none';
}

/** Change from `before` to `now`, both integer paise (or bill counts). */
export function change(now: number, before: number): Change {
  if (before <= 0) return { pct: null, direction: now > 0 ? 'up' : 'none' };
  const pct = Math.round(((now - before) / before) * 100);
  return { pct, direction: pct > 0 ? 'up' : pct < 0 ? 'down' : 'same' };
}

export const changeText = (c: Change): string =>
  c.pct === null ? (c.direction === 'up' ? 'new' : '') : `${c.pct > 0 ? '▲' : c.pct < 0 ? '▼' : '='} ${Math.abs(c.pct)}%`;

export interface DayTotal {
  business_date: string;
  bills: number;
  total_paise: number;
}

export interface WeekPair {
  date: string;
  now: number;
  before: number;
}

/** The last 14 days (oldest first) as 7 pairs: each of this week's days with the
 * same weekday a week earlier. Missing days count as nothing. */
export function weekPairs(days: DayTotal[], endDay: string, shift: (iso: string, n: number) => string): WeekPair[] {
  const by = new Map(days.map((d) => [d.business_date, d.total_paise]));
  const out: WeekPair[] = [];
  for (let n = 6; n >= 0; n--) {
    const date = shift(endDay, -n);
    out.push({ date, now: by.get(date) ?? 0, before: by.get(shift(date, -7)) ?? 0 });
  }
  return out;
}

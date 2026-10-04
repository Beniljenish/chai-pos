/** Pure helpers for the day-end screens (tested in dayend.test.ts). */
import { businessDate } from './billing';
import type { WastageReason } from './types';

export const REASONS: { id: WastageReason; label: string; ownerOnly?: boolean }[] = [
  { id: 'spoiled', label: 'Spoiled / expired' },
  { id: 'spilled', label: 'Spilled / dropped' },
  { id: 'remake', label: 'Remade (complaint)' },
  { id: 'prep_loss', label: 'Leftover thrown away' },
  { id: 'staff', label: 'Staff drink' },
  { id: 'complimentary', label: 'Free (on the house)', ownerOnly: true },
  { id: 'theft', label: 'Theft / unexplained', ownerOnly: true },
];

export const reasonLabel = (id: string) => REASONS.find((r) => r.id === id)?.label ?? id;

/** The two days a count can be for: today, or yesterday when closing after midnight. */
export function countableDays(now: Date): { date: string; label: string }[] {
  const today = businessDate(now);
  const yesterday = businessDate(new Date(now.getTime() - 24 * 3600 * 1000));
  const fmt = (iso: string) =>
    new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${iso}T00:00:00Z`));
  return [
    { date: today, label: `Today, ${fmt(today)}` },
    { date: yesterday, label: `Yesterday, ${fmt(yesterday)}` },
  ];
}

/** Daily and per-shift items must be counted; weekly ones may be skipped. */
export function mustCount(frequency: string): boolean {
  return frequency !== 'weekly';
}

/** Adherence for people: 88.9 -> "Used 12% more than the recipe". */
export function adherenceWords(pct: string | null): string | null {
  if (pct === null) return null;
  const n = Number(pct);
  if (n >= 99.5 && n <= 100.5) return 'Matches the recipe';
  const diff = Math.round(Math.abs(100 / n - 1) * 100);
  return n < 100 ? `Used ${diff}% more than the recipe` : `Used ${diff}% less than the recipe`;
}

export type TrendVerdict = 'few' | 'on' | 'steady' | 'varies';

/**
 * What a run of daily adherence numbers says about the cause.
 * A steady gap (every day off by about the same) points at the recipe; a gap
 * that jumps around points at the people on shift. Thresholds: within ±3 of
 * 100 is on recipe; a spread of more than 6 points between days is "varies".
 */
export function trendVerdict(points: (string | null)[]): TrendVerdict {
  const xs = points.filter((p): p is string => p !== null).map(Number);
  if (xs.length < 3) return 'few';
  const spread = Math.max(...xs) - Math.min(...xs);
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  if (spread > 6) return 'varies';
  return Math.abs(mean - 100) <= 3 ? 'on' : 'steady';
}

export const VERDICT_WORDS: Record<TrendVerdict, string> = {
  few: 'Too few closed days to tell',
  on: 'On recipe',
  steady: 'Steady gap: the recipe may need updating',
  varies: 'Changes day to day: look at who was on shift',
};

/**
 * Sparkline geometry: one x slot per closed day (gaps stay gaps), y from
 * `lo`% at the bottom to `hi`% at the top, values outside clamped to the edge.
 */
export function sparkPoints(
  days: string[],
  points: { business_date: string; adherence_pct: string | null }[],
  w: number,
  h: number,
  lo = 70,
  hi = 130,
): { x: number; y: number; date: string; pct: number }[] {
  const at = new Map(points.map((p) => [p.business_date, p.adherence_pct]));
  const step = days.length > 1 ? w / (days.length - 1) : 0;
  const out: { x: number; y: number; date: string; pct: number }[] = [];
  days.forEach((d, i) => {
    const v = at.get(d);
    if (v === null || v === undefined) return;
    const pct = Number(v);
    const c = Math.min(hi, Math.max(lo, pct));
    out.push({ x: days.length > 1 ? i * step : w / 2, y: h - ((c - lo) / (hi - lo)) * h, date: d, pct });
  });
  return out;
}

/** Where 100% sits on a sparkline of height h (same scale as sparkPoints). */
export const sparkY100 = (h: number, lo = 70, hi = 130) => h - ((100 - lo) / (hi - lo)) * h;

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

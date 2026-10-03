/** Sales report and voids: pure helpers, tested in sales.test.ts. */

export type VoidReason = 'wrong_item' | 'duplicate' | 'payment_failed' | 'customer_cancelled' | 'other';

export const VOID_REASONS: { id: VoidReason; label: string }[] = [
  { id: 'wrong_item', label: 'Wrong item tapped' },
  { id: 'duplicate', label: 'Billed twice' },
  { id: 'payment_failed', label: 'Payment failed' },
  { id: 'customer_cancelled', label: 'Customer cancelled' },
  { id: 'other', label: 'Other' },
];

export const voidReasonLabel = (id: string) => VOID_REASONS.find((r) => r.id === id)?.label ?? id;

export const PAYMENT_LABELS: Record<string, string> = { cash: 'Cash', upi: 'UPI', card: 'Card' };

/** "2026-10-03" plus n days, in plain calendar arithmetic (no time zones involved). */
export function shiftDay(iso: string, n: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}

/** "Today", "Yesterday", or "Thu 1 Oct". */
export function dayLabel(iso: string, today: string): string {
  if (iso === today) return 'Today';
  if (iso === shiftDay(today, -1)) return 'Yesterday';
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat('en-IN', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

/** 0 -> "12 am", 7 -> "7 am", 12 -> "12 pm", 19 -> "7 pm". */
export function hourLabel(h: number): string {
  const suffix = h < 12 ? 'am' : 'pm';
  const twelve = h % 12 === 0 ? 12 : h % 12;
  return `${twelve} ${suffix}`;
}

export interface HourRow {
  hour: number;
  bills: number;
  total_paise: number;
}

/** Every hour from the first sale to the last (quiet hours shown as zero), with
 * each bar's width as a share of the busiest hour. */
export function hourBars(rows: HourRow[]): (HourRow & { pct: number })[] {
  if (rows.length === 0) return [];
  const by = new Map(rows.map((r) => [r.hour, r]));
  const first = Math.min(...rows.map((r) => r.hour));
  const last = Math.max(...rows.map((r) => r.hour));
  const max = Math.max(...rows.map((r) => r.total_paise), 1);
  const out = [];
  for (let h = first; h <= last; h++) {
    const r = by.get(h) ?? { hour: h, bills: 0, total_paise: 0 };
    out.push({ ...r, pct: Math.round((r.total_paise / max) * 100) });
  }
  return out;
}

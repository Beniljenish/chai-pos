/** Types and small helpers for the Watch screen (UPI match, changes, GST limit): README, "9.16". */

export interface UpiMiss {
  bill_id: string;
  invoice_no: string;
  sold_at: string;
  cashier: string;
  upi_paise: number;
  state: 'none' | 'created' | 'failed';
}

export interface UpiMatch {
  from: string;
  to: string;
  online_on: boolean;
  upi_bills: number;
  upi_billed_paise: number;
  confirmed_paise: number;
  unconfirmed: UpiMiss[];
  differs: { bill_id: string; invoice_no: string; cashier: string; upi_paise: number; paid_paise: number }[];
  paid_for_void: { bill_id: string; invoice_no: string; paid_paise: number }[];
  by_cashier: { name: string; upi_bills: number; unconfirmed: number; unconfirmed_paise: number }[];
}

export interface Fact {
  at: string;
  kind: string;
  title: string;
  detail: string;
  by: string;
  amount_paise: number | null;
}

export interface ChangeRow extends Fact {
  bill_id: string | null;
  order_id: string | null;
}

export interface Changes {
  date: string;
  rows: ChangeRow[];
  counts: Record<string, number>;
}

export type GstStatus = 'registered' | 'no_threshold' | 'safe' | 'watch' | 'over';

export interface GstWatch {
  status: GstStatus;
  fy_from: string;
  fy_to: string;
  turnover_paise: number;
  threshold_paise: number | null;
  percent: number | null;
  daily_paise: number;
  cross_on: string | null;
}

/** The YYYY-MM-DD that is `back` days before `day` (both plain calendar dates). */
export function daysBefore(day: string, back: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - back);
  return d.toISOString().slice(0, 10);
}

/** What the UPI match found, in one line for the top of the screen. */
export function upiVerdict(m: UpiMatch): 'off' | 'clean' | 'check' {
  if (!m.online_on) return 'off';
  return m.unconfirmed.length + m.differs.length + m.paid_for_void.length === 0 ? 'clean' : 'check';
}

/** How full the GST limit bar is, 0..100 (the number itself can pass 100). */
export const barPercent = (percent: number | null): number => Math.max(0, Math.min(100, percent ?? 0));

/** "20,00,000" or "2000000" typed in rupees to paise, or null if it is not a whole-rupee amount. */
export function limitToPaise(text: string): number | null {
  const digits = text.replace(/[,\s]/g, '');
  if (!/^\d{1,9}$/.test(digits)) return null;
  const rupees = Number(digits);
  return rupees > 0 ? rupees * 100 : null;
}

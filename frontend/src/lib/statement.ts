/**
 * An outlet's statement from the food court: what was sold online, what went back to
 * customers, the food court's fee and what is still owed. Pure helpers (README, "9.17").
 */
import { csvRupees } from './reports';

export interface StatementOrder {
  date: string;
  token: string;
  paid_paise: number;
  cancelled: boolean;
  refunded_paise: number;
  refund_pending: boolean;
  fee_paise: number;
}

export interface Statement {
  from: string;
  to: string;
  fee_bp: number;
  orders: StatementOrder[];
  sales_paise: number;
  refunds_paise: number;
  fee_paise: number;
  earned_paise: number;
  paid_out: { date: string; amount_paise: number; note: string }[];
  paid_out_paise: number;
  owed_now_paise: number;
}

/** 500 -> "5%", 250 -> "2.5%". */
export const feePercent = (bp: number) => `${bp % 100 === 0 ? bp / 100 : (bp / 100).toFixed(2).replace(/0$/, '')}%`;

/** "5", "2.5" -> basis points; null when it is not a sensible percentage (0 to 30). */
export function percentToBp(text: string): number | null {
  const t = text.trim().replace('%', '');
  if (!/^\d{1,2}(\.\d{1,2})?$/.test(t)) return null;
  const bp = Math.round(Number(t) * 100);
  return bp >= 0 && bp <= 3000 ? bp : null;
}

/** The statement as spreadsheet rows: a line per order, then the totals. */
export function statementRows(s: Statement): (string | number)[][] {
  return [
    ['Date', 'Token', 'Paid by customer', 'Fee', 'Cancelled', 'Refunded'],
    ...s.orders.map((o) => [
      o.date,
      o.token,
      csvRupees(o.paid_paise),
      csvRupees(o.fee_paise),
      o.cancelled ? 'yes' : '',
      csvRupees(o.refunded_paise),
    ]),
    [],
    ['Sales', csvRupees(s.sales_paise)],
    ['Fee', csvRupees(s.fee_paise)],
    ['Earned', csvRupees(s.earned_paise)],
    ['Refunded to customers', csvRupees(s.refunds_paise)],
    ['Paid to you in this range', csvRupees(s.paid_out_paise)],
    ['Still due to you now', csvRupees(s.owed_now_paise)],
  ];
}

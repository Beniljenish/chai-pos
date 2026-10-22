/** The food court operator's overview (README, "9.21"): types, the heatmap's shading, the CSV. */
import { csvRupees } from './reports';

export interface OutletRow {
  outlet_id: string;
  name: string;
  fee_bp: number;
  rating: number | null;
  rating_count: number;
  orders: number;
  cancelled: number;
  cancel_rate_pct: number | null;
  sales_paise: number;
  fee_paise: number;
  refunds_paise: number;
  avg_wait_min: number | null;
}

export interface CourtOverview {
  court_id: string;
  court: string;
  outlets: OutletRow[];
  totals: { sales_paise: number; fee_paise: number; orders: number };
  heatmap: number[][]; // 7 weekdays (Monday first) x 24 hours
  busiest: { weekday: string; hour: number; orders: number }[];
}

export interface Overview {
  from: string;
  to: string;
  courts: CourtOverview[];
}

export interface SettlementRow {
  court: string;
  outlet: string;
  owner: string;
  owner_phone: string;
  paid_paise: number;
  fee_paise: number;
  settled_paise: number;
  owed_paise: number;
}

/** "13:00-14:00" as people say it: "1 pm". */
export const hourLabel = (h: number): string => `${h % 12 === 0 ? 12 : h % 12} ${h < 12 ? 'am' : 'pm'}`;

/** How dark a heatmap cell is, 0 (none) to 4, relative to the busiest cell. */
export function shade(n: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (n <= 0 || max <= 0) return 0;
  return Math.min(4, Math.max(1, Math.ceil((n / max) * 4))) as 1 | 2 | 3 | 4;
}

/** The sheet the operator pays from: only outlets that are owed something, biggest first. */
export function settlementCsv(rows: SettlementRow[]): (string | number)[][] {
  const owed = rows.filter((r) => r.owed_paise > 0).sort((a, b) => b.owed_paise - a.owed_paise);
  return [
    ['Food court', 'Outlet', 'Owner', 'Owner phone', 'Paid by customers', 'Fee kept', 'Already paid out', 'Owed now'],
    ...owed.map((r) => [
      r.court,
      r.outlet,
      r.owner,
      r.owner_phone,
      csvRupees(r.paid_paise),
      csvRupees(r.fee_paise),
      csvRupees(r.settled_paise),
      csvRupees(r.owed_paise),
    ]),
    [],
    ['Total owed', '', '', '', '', '', '', csvRupees(owed.reduce((n, r) => n + r.owed_paise, 0))],
  ];
}

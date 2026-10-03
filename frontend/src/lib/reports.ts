/**
 * Owner reports and purchasing (README, "Phase 7"): pure helpers, tested in
 * reports.test.ts. Date ranges, CSV files that open cleanly in Excel, the GST
 * summary as tables, and quantities typed in the unit people buy in.
 */
import { shiftDay } from './sales';
import type { BaseUnit } from './qty';

export interface Range {
  from: string;
  to: string;
  label: string;
}

/** Quick ranges, from the shop's today ("2026-10-04"). Weeks start on Monday. */
export function presets(today: string): Range[] {
  const [y, m, d] = today.split('-').map(Number);
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // Monday = 0
  const monthStart = `${today.slice(0, 7)}-01`;
  const lastMonthEnd = shiftDay(monthStart, -1);
  return [
    { label: 'Last 7 days', from: shiftDay(today, -6), to: today },
    { label: 'This week', from: shiftDay(today, -weekday), to: today },
    { label: 'This month', from: monthStart, to: today },
    { label: 'Last month', from: `${lastMonthEnd.slice(0, 7)}-01`, to: lastMonthEnd },
  ];
}

/** Paise as plain rupees for a spreadsheet: 1904 -> "19.04" (no ₹, no commas). */
export const csvRupees = (paise: number) => `${paise < 0 ? '-' : ''}${Math.floor(Math.abs(paise) / 100)}.${String(Math.abs(paise) % 100).padStart(2, '0')}`;

/** A CSV file with a BOM, so Excel shows names and ₹ correctly; quotes as needed. */
export function toCsv(rows: (string | number)[][]): string {
  const cell = (v: string | number) => {
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '﻿' + rows.map((r) => r.map(cell).join(',')).join('\r\n') + '\r\n';
}

export interface GstSummary {
  month: string;
  gst_type: string;
  gstin: string | null;
  state_code: string;
  b2cs: { place_of_supply: string; rate_bp: number; taxable_paise: number; cgst_paise: number; sgst_paise: number }[];
  nil_rated_paise: number;
  hsn: {
    hsn_sac: string;
    description: string;
    uqc: string;
    rate_bp: number;
    qty: number;
    taxable_paise: number;
    cgst_paise: number;
    sgst_paise: number;
    total_paise: number;
  }[];
  documents: { series: string; from: string; to: string; total: number; cancelled: number; missing: number; net_issued: number }[];
  totals: { invoices: number; invoice_value_paise: number; taxable_paise: number; cgst_paise: number; sgst_paise: number };
}

const rate = (bp: number) => String(bp / 100);

/** The GST summary as the three GSTR-1 tables, ready for toCsv. */
export function gstTables(g: GstSummary): Record<'b2cs' | 'hsn' | 'docs', (string | number)[][]> {
  return {
    b2cs: [
      ['Type', 'Place of supply', 'Rate (%)', 'Taxable value', 'CGST', 'SGST', 'Cess'],
      ...g.b2cs.map((r) => ['OE', r.place_of_supply, rate(r.rate_bp), csvRupees(r.taxable_paise), csvRupees(r.cgst_paise), csvRupees(r.sgst_paise), '0.00']),
    ],
    hsn: [
      ['HSN/SAC', 'Description', 'UQC', 'Total quantity', 'Rate (%)', 'Total value', 'Taxable value', 'CGST', 'SGST', 'Cess'],
      ...g.hsn.map((r) => [
        r.hsn_sac,
        r.description,
        r.uqc,
        r.qty,
        rate(r.rate_bp),
        csvRupees(r.total_paise),
        csvRupees(r.taxable_paise),
        csvRupees(r.cgst_paise),
        csvRupees(r.sgst_paise),
        '0.00',
      ]),
    ],
    docs: [
      ['Nature of document', 'Sr. No. From', 'Sr. No. To', 'Total number', 'Cancelled', 'Net issued', 'Not on server'],
      ...g.documents.map((d) => ['Invoices for outward supply', d.from, d.to, d.total, d.cancelled, d.net_issued, d.missing]),
    ],
  };
}

/** The unit people buy in: litres, kilograms, pieces. */
export const buyUnit = (u: BaseUnit) => (u === 'ml' ? 'L' : u === 'g' ? 'kg' : 'pcs');

/** "1.5" L -> "1500.000" ml (exact, as a string for the server); "" if not a number. */
export function toBaseQty(typed: string, u: BaseUnit): string {
  const shift = u === 'piece' ? 0 : 3; // litres/kilos to ml/g
  const m = /^(\d*)(?:\.(\d*))?$/.exec(typed.trim());
  if (!m || (m[1] === '' && !m[2]) || (m[2] ?? '').length > shift + 3) return '';
  // value x 10^(shift+3) = the base quantity in thousandths
  const thousandths = BigInt((m[1] || '0') + (m[2] ?? '').padEnd(shift + 3, '0')).toString().padStart(4, '0');
  return `${thousandths.slice(0, -3)}.${thousandths.slice(-3)}`;
}

/** "1500.000" ml -> "1.5" (in the buying unit). */
export function fromBaseQty(base: string, u: BaseUnit): string {
  const n = Number(base) / (u === 'piece' ? 1 : 1000);
  return String(Math.round(n * 1000) / 1000);
}

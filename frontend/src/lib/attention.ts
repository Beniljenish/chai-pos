/** What needs the owner, as counts for Manage: pure, tested in attention.test.ts. */
import { t } from './i18n';

export interface Attention {
  /** Stock rows below their reorder level, or below zero. */
  lowStock: number;
  /** Day-end items waiting on the owner: pending wastage plus submitted counts. */
  toApprove: number;
  /** Alerts worth acting on or a look (not news, and not waiting wastage: Day end shows that). */
  alerts: number;
  /** Customers who owe money (the khata has no due dates, so "owe" not "overdue"). */
  owing: number;
}

export const NO_ATTENTION: Attention = { lowStock: 0, toApprove: 0, alerts: 0, owing: 0 };

export const attentionTotal = (a: Attention): number => a.lowStock + a.toApprove + a.alerts + a.owing;

export type Urgency = 'act' | 'look';

/** Manage row id -> badge text and colour; rows with nothing to say are absent. */
export function badgesFor(a: Attention): Record<string, { text: string; urgency: Urgency }> {
  const out: Record<string, { text: string; urgency: Urgency }> = {};
  if (a.alerts > 0) out.alerts = { text: t('{n} new', { n: a.alerts }), urgency: 'act' };
  if (a.lowStock > 0) out.stock = { text: t('{n} low', { n: a.lowStock }), urgency: 'act' };
  if (a.toApprove > 0) out.dayend = { text: t('{n} to approve', { n: a.toApprove }), urgency: 'act' };
  if (a.owing > 0) out.khata = { text: a.owing === 1 ? t('1 owes') : t('{n} owe', { n: a.owing }), urgency: 'look' };
  return out;
}

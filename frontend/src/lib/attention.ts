/** What needs the owner, as counts for Manage: pure, tested in attention.test.ts. */

export interface Attention {
  /** Stock rows below their reorder level, or below zero. */
  lowStock: number;
  /** Day-end items waiting on the owner: pending wastage plus submitted counts. */
  toApprove: number;
  /** Customers who owe money (the khata has no due dates, so "owe" not "overdue"). */
  owing: number;
}

export const NO_ATTENTION: Attention = { lowStock: 0, toApprove: 0, owing: 0 };

export const attentionTotal = (a: Attention): number => a.lowStock + a.toApprove + a.owing;

export type Urgency = 'act' | 'look';

/** Manage row id -> badge text and colour; rows with nothing to say are absent. */
export function badgesFor(a: Attention): Record<string, { text: string; urgency: Urgency }> {
  const out: Record<string, { text: string; urgency: Urgency }> = {};
  if (a.lowStock > 0) out.stock = { text: `${a.lowStock} low`, urgency: 'act' };
  if (a.toApprove > 0) out.dayend = { text: `${a.toApprove} to approve`, urgency: 'act' };
  if (a.owing > 0) out.khata = { text: `${a.owing} owe${a.owing === 1 ? 's' : ''}`, urgency: 'look' };
  return out;
}

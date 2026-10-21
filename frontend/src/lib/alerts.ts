/** The alerts list: pure helpers, tested in alerts.test.ts. */
import type { AlertItem } from './types';

export const URGENCY_LABEL: Record<AlertItem['urgency'], string> = {
  act: 'Act now',
  look: 'Take a look',
  info: 'Good to know',
};

/** Today's alerts, then the week's, each keeping the server's most-urgent-first order. */
export function groupAlerts(items: AlertItem[]): { label: string; items: AlertItem[] }[] {
  const groups = [
    { label: 'Today', items: items.filter((a) => a.period === 'today') },
    { label: 'This week', items: items.filter((a) => a.period === 'week') },
  ];
  return groups.filter((g) => g.items.length > 0);
}

/** Alerts that already have a Manage row of their own are not counted twice in the
 * badges: a waiting wastage entry already shows on Day end. */
export const countsForBadge = (a: AlertItem): boolean => a.urgency !== 'info' && a.kind !== 'wastage_pending';

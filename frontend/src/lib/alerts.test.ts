import { describe, expect, it } from 'vitest';
import { countsForBadge, groupAlerts } from './alerts';
import type { AlertItem } from './types';

const a = (kind: string, urgency: AlertItem['urgency'], period: AlertItem['period']): AlertItem => ({
  id: kind,
  kind,
  urgency,
  period,
  title: kind,
  detail: '',
  at: null,
  section: 'sales',
});

describe('groupAlerts', () => {
  it('splits today from this week and drops an empty group', () => {
    const g = groupAlerts([a('drawer_short', 'act', 'today'), a('price_up', 'info', 'week')]);
    expect(g.map((x) => [x.label, x.items.length])).toEqual([
      ['Today', 1],
      ['This week', 1],
    ]);
    expect(groupAlerts([a('price_up', 'info', 'week')]).map((x) => x.label)).toEqual(['This week']);
    expect(groupAlerts([])).toEqual([]);
  });
});

describe('countsForBadge', () => {
  it('counts what needs action or a look, not news', () => {
    expect(countsForBadge(a('void_burst', 'act', 'today'))).toBe(true);
    expect(countsForBadge(a('discounts', 'look', 'today'))).toBe(true);
    expect(countsForBadge(a('price_up', 'info', 'week'))).toBe(false);
  });
  it('leaves out waiting wastage, which Day end already shows', () => {
    expect(countsForBadge(a('wastage_pending', 'act', 'today'))).toBe(false);
  });
});

import { describe, expect, it } from 'vitest';
import { hourLabel, settlementCsv, shade, type SettlementRow } from './operator';

describe('operator overview', () => {
  it('says hours the way people do', () => {
    expect(hourLabel(0)).toBe('12 am');
    expect(hourLabel(12)).toBe('12 pm');
    expect(hourLabel(13)).toBe('1 pm');
    expect(hourLabel(23)).toBe('11 pm');
  });

  it('shades a cell against the busiest one', () => {
    expect(shade(0, 10)).toBe(0);
    expect(shade(1, 10)).toBe(1);
    expect(shade(5, 10)).toBe(2);
    expect(shade(10, 10)).toBe(4);
    expect(shade(3, 0)).toBe(0);
  });

  it('lists only outlets that are owed, biggest first, with a total', () => {
    const row = (outlet: string, owed: number): SettlementRow => ({
      court: 'Marina',
      outlet,
      owner: 'Anna',
      owner_phone: '9841155555',
      paid_paise: owed + 100,
      fee_paise: 100,
      settled_paise: 0,
      owed_paise: owed,
    });
    const rows = settlementCsv([row('Small', 5000), row('None', 0), row('Big', 250000)]);
    expect(rows.slice(1, 3).map((r) => r[1])).toEqual(['Big', 'Small']);
    expect(rows[1][7]).toBe('2500.00');
    expect(rows[rows.length - 1]).toEqual(['Total owed', '', '', '', '', '', '', '2550.00']);
  });
});

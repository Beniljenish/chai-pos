import { describe, expect, it } from 'vitest';
import { feePercent, percentToBp, statementRows, type Statement } from './statement';

describe('statement helpers', () => {
  it('shows basis points as a percentage', () => {
    expect(feePercent(500)).toBe('5%');
    expect(feePercent(250)).toBe('2.5%');
    expect(feePercent(0)).toBe('0%');
  });

  it('reads a typed percentage, refusing nonsense and more than 30', () => {
    expect(percentToBp('5')).toBe(500);
    expect(percentToBp('2.5%')).toBe(250);
    expect(percentToBp('31')).toBeNull();
    expect(percentToBp('abc')).toBeNull();
    expect(percentToBp('')).toBeNull();
  });

  it('writes every order and the totals as rupees', () => {
    const s: Statement = {
      from: '2026-10-01',
      to: '2026-10-07',
      fee_bp: 500,
      orders: [
        { date: '2026-10-01', token: 'A12', paid_paise: 2000, cancelled: false, refunded_paise: 0, refund_pending: false, fee_paise: 100 },
        { date: '2026-10-02', token: 'A13', paid_paise: 1000, cancelled: true, refunded_paise: 1000, refund_pending: false, fee_paise: 0 },
      ],
      sales_paise: 2000,
      refunds_paise: 1000,
      fee_paise: 100,
      earned_paise: 1900,
      paid_out: [],
      paid_out_paise: 0,
      owed_now_paise: 1900,
    };
    const rows = statementRows(s);
    expect(rows[1]).toEqual(['2026-10-01', 'A12', '20.00', '1.00', '', '0.00']);
    expect(rows[2]).toEqual(['2026-10-02', 'A13', '10.00', '0.00', 'yes', '10.00']);
    expect(rows).toContainEqual(['Still due to you now', '19.00']);
  });
});

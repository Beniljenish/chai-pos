import { describe, expect, it } from 'vitest';
import { barPercent, daysBefore, limitToPaise, upiVerdict, type UpiMatch } from './watch';

const match = (over: Partial<UpiMatch> = {}): UpiMatch => ({
  from: '2026-10-15',
  to: '2026-10-21',
  online_on: true,
  upi_bills: 0,
  upi_billed_paise: 0,
  confirmed_paise: 0,
  unconfirmed: [],
  differs: [],
  paid_for_void: [],
  by_cashier: [],
  ...over,
});

describe('the UPI match verdict', () => {
  it('says there is nothing to compare when Razorpay is not used', () => {
    expect(upiVerdict(match({ online_on: false }))).toBe('off');
  });
  it('is clean with no problems and "check" with any', () => {
    expect(upiVerdict(match())).toBe('clean');
    expect(upiVerdict(match({ paid_for_void: [{ bill_id: 'b', invoice_no: 'C1/1', paid_paise: 100 }] }))).toBe('check');
  });
});

describe('dates and limits', () => {
  it('counts calendar days back across a month end', () => {
    expect(daysBefore('2026-10-21', 6)).toBe('2026-10-15');
    expect(daysBefore('2026-03-02', 3)).toBe('2026-02-27');
  });
  it('turns a typed limit into paise with no floats', () => {
    expect(limitToPaise('20,00,000')).toBe(200_000_000);
    expect(limitToPaise(' 4000000 ')).toBe(400_000_000);
    expect(limitToPaise('0')).toBeNull();
    expect(limitToPaise('12.5')).toBeNull();
    expect(limitToPaise('lots')).toBeNull();
  });
  it('keeps the bar inside its box', () => {
    expect(barPercent(null)).toBe(0);
    expect(barPercent(47)).toBe(47);
    expect(barPercent(130)).toBe(100);
  });
});

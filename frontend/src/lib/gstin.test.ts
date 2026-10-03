import { describe, expect, it } from 'vitest';
import { formatRate, taxByRate } from './gst';
import { checkDigit, checkGstin } from './gstin';

describe('GSTIN (same vectors as backend/tests/test_shop_gst.py)', () => {
  it.each(['27AAPFU0939F1ZV', '29AAGCB7383J1Z4', '33ABCDE1234F1Z7'])('accepts %s', (g) => {
    expect(checkDigit(g.slice(0, 14))).toBe(g[14]);
    expect(checkGstin(g).ok).toBe(true);
  });
  it('names the state and tidies input', () => {
    expect(checkGstin(' 27aapfu0939f1zv ')).toEqual({ ok: true, gstin: '27AAPFU0939F1ZV', state: 'Maharashtra' });
  });
  it('catches one mistyped character', () => {
    const r = checkGstin('27AAPFU0839F1ZV');
    expect(r.ok).toBe(false);
    expect(!r.ok && r.reason).toMatch(/mistyped/);
  });
  it('explains short, malformed and bad-state input', () => {
    expect(checkGstin('27AAPFU').ok).toBe(false);
    expect(!checkGstin('27AAPFU0939F1XV').ok).toBe(true);
    const bad = checkGstin('40AAPFU0939F1ZV');
    expect(!bad.ok && bad.reason).toMatch(/state code/);
  });
});

describe('tax by rate (printed on tax invoices)', () => {
  it('groups lines by rate and skips untaxed ones', () => {
    const lines = [
      { gst_rate_bp: 500, totals: { taxable: 1905, cgst: 48, sgst: 47 } },
      { gst_rate_bp: 1800, totals: { taxable: 4237, cgst: 382, sgst: 381 } },
      { gst_rate_bp: 500, totals: { taxable: 1905, cgst: 48, sgst: 47 } },
      { gst_rate_bp: 0, totals: { taxable: 1000, cgst: 0, sgst: 0 } },
    ];
    expect(taxByRate(lines)).toEqual([
      { rateBp: 500, taxable: 3810, cgst: 96, sgst: 94 },
      { rateBp: 1800, taxable: 4237, cgst: 382, sgst: 381 },
    ]);
    expect(formatRate(250)).toBe('2.5%');
    expect(formatRate(900)).toBe('9%');
  });
});

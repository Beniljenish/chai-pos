import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { computeBill, formatRupees, GstError, type GstType, type LineIn } from './gst';

// The SAME file the Python implementation is tested against.
const vectors = JSON.parse(
  readFileSync(resolve(__dirname, '../../../shared/gst_cases.json'), 'utf8'),
);

type RawLine = {
  unit_price_paise: number;
  qty: number;
  gst_rate_bp: number;
  tax_inclusive: boolean;
  modifier_deltas_paise?: number[];
  discount_paise?: number;
};

const toLines = (raw: RawLine[]): LineIn[] =>
  raw.map((r) => ({
    unitPricePaise: r.unit_price_paise,
    qty: r.qty,
    gstRateBp: r.gst_rate_bp,
    taxInclusive: r.tax_inclusive,
    modifierDeltasPaise: r.modifier_deltas_paise ?? [],
    discountPaise: r.discount_paise ?? 0,
  }));

describe('shared GST vectors (same file as the Python tests)', () => {
  for (const c of vectors.cases) {
    it(c.name, () => {
      const bill = computeBill(toLines(c.lines), c.gst_type as GstType, c.bill_discount_paise ?? 0);
      expect(bill.lines).toEqual(c.expect_lines);
      const { lines: _lines, roundOff, ...rest } = bill;
      expect({ ...rest, round_off: roundOff }).toEqual(c.expect_bill);
    });
  }
  for (const c of vectors.errors) {
    it(`rejects: ${c.name}`, () => {
      expect(() => computeBill(toLines(c.lines), c.gst_type as GstType, c.bill_discount_paise ?? 0)).toThrow(GstError);
    });
  }
});

describe('invariants over 5000 random bills', () => {
  it('always add up', () => {
    let seed = 42;
    const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
    const pick = <T,>(xs: T[]) => xs[Math.floor(rnd() * xs.length)];
    for (let i = 0; i < 5000; i++) {
      const lines: LineIn[] = Array.from({ length: 1 + Math.floor(rnd() * 6) }, () => ({
        unitPricePaise: pick([0, 1, 99, 1000, 1050, 2000, 3333, 6000, Math.floor(rnd() * 50_000)]),
        qty: 1 + Math.floor(rnd() * 20),
        gstRateBp: pick([0, 25, 300, 500, 1200, 1800, 2800]),
        taxInclusive: rnd() < 0.7,
        modifierDeltasPaise: [pick([0, 500, 1000])],
      }));
      const type = pick<GstType>(['regular', 'composition', 'unregistered']);
      const bill = computeBill(lines, type);
      bill.lines.forEach((lt, j) => {
        expect(lt.taxable + lt.cgst + lt.sgst).toBe(lt.total);
        expect(lt.cgst).toBe(lt.sgst);
        if (type === 'regular' && lines[j].taxInclusive) expect(lt.total).toBe(lt.gross);
      });
      expect(bill.total % 100).toBe(0);
      expect(bill.roundOff).toBeGreaterThanOrEqual(-49);
      expect(bill.roundOff).toBeLessThanOrEqual(50);
      expect(bill.taxable + bill.cgst + bill.sgst).toBe(bill.subtotal);
    }
  });
});

describe('formatRupees', () => {
  it('formats Indian style', () => {
    expect(formatRupees(2000)).toBe('₹20');
    expect(formatRupees(2050)).toBe('₹20.50');
    expect(formatRupees(12345600)).toBe('₹1,23,456');
    expect(formatRupees(-5)).toBe('-₹0.05');
  });
});

describe('Python/TypeScript cross-check: 2000 random bills', () => {
  // shared/gst_crosscheck.json holds the PYTHON answers (scripts/gen_gst_crosscheck.py).
  // Any difference here would show up as a totals_mismatch on real bills.
  const cross = JSON.parse(
    readFileSync(resolve(__dirname, '../../../shared/gst_crosscheck.json'), 'utf8'),
  );
  it('TypeScript reproduces every Python answer exactly', () => {
    let checked = 0;
    for (const c of cross.cases) {
      const bill = computeBill(toLines(c.lines), c.gst_type as GstType);
      expect(bill.lines.map((l) => [l.gross, l.taxable, l.cgst, l.sgst, l.total])).toEqual(
        c.expect.lines,
      );
      expect([bill.taxable, bill.cgst, bill.sgst, bill.subtotal, bill.roundOff, bill.total]).toEqual(
        c.expect.bill,
      );
      checked++;
    }
    expect(checked).toBe(2000);
  });

  it('and every Python answer for 1000 bills with line and bill discounts', () => {
    let checked = 0;
    for (const c of cross.discount_cases) {
      const bill = computeBill(toLines(c.lines), c.gst_type as GstType, c.bill_discount_paise);
      expect(bill.lines.map((l) => [l.gross, l.discount, l.taxable, l.cgst, l.sgst, l.total])).toEqual(c.expect.lines);
      expect([bill.discount, bill.taxable, bill.cgst, bill.sgst, bill.subtotal, bill.roundOff, bill.total]).toEqual(
        c.expect.bill,
      );
      checked++;
    }
    expect(checked).toBe(1000);
  });
});

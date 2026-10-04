import { describe, expect, it } from 'vitest';
import { buyUnit, csvRupees, fromBaseQty, gstTables, presets, toBaseQty, toCsv, type GstSummary } from './reports';

describe('date presets', () => {
  it('weeks start on Monday; last month is the whole of it', () => {
    // 4 Oct 2026 is a Sunday.
    expect(presets('2026-10-04')).toEqual([
      { label: 'Last 7 days', from: '2026-09-28', to: '2026-10-04' },
      { label: 'This week', from: '2026-09-28', to: '2026-10-04' },
      { label: 'This month', from: '2026-10-01', to: '2026-10-04' },
      { label: 'Last month', from: '2026-09-01', to: '2026-09-30' },
    ]);
    expect(presets('2027-03-01')[3]).toEqual({ label: 'Last month', from: '2027-02-01', to: '2027-02-28' });
    expect(presets('2026-10-05')[1].from).toBe('2026-10-05'); // a Monday
  });
});

describe('CSV', () => {
  it('rupees without symbols, cells quoted only when needed, BOM for Excel', () => {
    expect([csvRupees(1904), csvRupees(5), csvRupees(-250), csvRupees(123400)]).toEqual(['19.04', '0.05', '-2.50', '1234.00']);
    expect(toCsv([['Name', 'Note'], ['Tea, masala', 'said "hot"']])).toBe('﻿Name,Note\r\n"Tea, masala","said ""hot"""\r\n');
  });

  it('GST summary as the three GSTR-1 tables', () => {
    const g: GstSummary = {
      month: '2026-10',
      gst_type: 'regular',
      gstin: '33ABCDE1234F1Z7',
      state_code: '33',
      b2cs: [{ place_of_supply: '33', rate_bp: 500, taxable_paise: 9523, cgst_paise: 238, sgst_paise: 238 }],
      nil_rated_paise: 0,
      hsn: [
        { hsn_sac: '996331', description: 'Masala tea, Orange juice', uqc: 'NOS', rate_bp: 500, qty: 3, taxable_paise: 9523, cgst_paise: 238, sgst_paise: 238, total_paise: 10000 },
      ],
      documents: [{ series: 'C1/26-27', from: 'C1/26-27/000001', to: 'C1/26-27/000003', total: 3, cancelled: 1, missing: 0, net_issued: 2 }],
      totals: { invoices: 2, invoice_value_paise: 10000, taxable_paise: 9523, cgst_paise: 238, sgst_paise: 238 },
    };
    const t = gstTables(g);
    expect(t.b2cs[1]).toEqual(['OE', '33', '5', '95.23', '2.38', '2.38', '0.00']);
    expect(t.hsn[1]).toEqual(['996331', 'Masala tea, Orange juice', 'NOS', 3, '5', '100.00', '95.23', '2.38', '2.38', '0.00']);
    expect(t.docs[1]).toEqual(['Invoices for outward supply', 'C1/26-27/000001', 'C1/26-27/000003', 3, 1, 2, 0]);
  });
});

describe('quantities in the buying unit', () => {
  it('litres and kilos to base units, exactly', () => {
    expect(buyUnit('ml')).toBe('L');
    expect(toBaseQty('1.5', 'ml')).toBe('1500.000');
    expect(toBaseQty('10', 'g')).toBe('10000.000');
    expect(toBaseQty('0.255', 'ml')).toBe('255.000');
    expect(toBaseQty('12', 'piece')).toBe('12.000');
    expect(toBaseQty('1.5.2', 'ml')).toBe('');
    expect(fromBaseQty('1500.000', 'ml')).toBe('1.5');
    expect(fromBaseQty('12.000', 'piece')).toBe('12');
  });
});

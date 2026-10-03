import { describe, expect, it } from 'vitest';
import { formatDelta, formatQty, packsPayload, packsToBase } from './qty';

describe('formatQty', () => {
  it('uses litres and kilos once a quantity reaches one of them', () => {
    expect(formatQty('1700', 'ml')).toBe('1.7 L');
    expect(formatQty('999', 'ml')).toBe('999 ml');
    expect(formatQty('5833.338', 'g')).toBe('5.833 kg');
    expect(formatQty('17', 'piece')).toBe('17 pcs');
  });
  it('shows negative stock as negative, in the same units', () => {
    expect(formatQty('-300', 'ml')).toBe('-300 ml');
    expect(formatQty('-5833.338', 'g')).toBe('-5.833 kg');
  });
});

describe('formatDelta', () => {
  it('signs ledger movements', () => {
    expect(formatDelta('2000', 'ml')).toBe('+2 L');
    expect(formatDelta('-150', 'ml')).toBe('−150 ml');
  });
});

describe('packsToBase', () => {
  const units = [
    { id: 'packet', name: 'packet', qty_in_base: '500.000' },
    { id: 'crate', name: 'crate', qty_in_base: '12000.000' },
  ];
  it('adds packs and loose quantity', () => {
    expect(packsToBase(units, { packet: 3 }, 200)).toBe(1700);
    expect(packsToBase(units, { crate: 1, packet: 2 }, 0)).toBe(13000);
  });
  it('does not drift on fractional packs', () => {
    expect(packsToBase([{ id: 'x', name: 'x', qty_in_base: '555.556' }], { x: 3 }, 0)).toBe(1666.668);
  });
  it('sends only packs that were entered', () => {
    expect(packsPayload({ packet: 3, crate: 0 })).toEqual([{ pack_unit_id: 'packet', qty: '3' }]);
  });
});

import { describe, expect, it } from 'vitest';
import { commission, percentToBp, share } from './commission';

describe('commission calculator', () => {
  it('reads a typed percentage', () => {
    expect(percentToBp('25')).toBe(2500);
    expect(percentToBp('2.5%')).toBe(250);
    expect(percentToBp('101')).toBeNull();
    expect(percentToBp('x')).toBeNull();
  });

  it('rounds half up, in paise', () => {
    expect(share(1, 5000)).toBe(1); // 0.5 paise rounds up
    expect(share(4_000_000, 2500)).toBe(1_000_000);
  });

  it('compares what the apps take with what direct orders would cost', () => {
    expect(commission(4_000_000, 2500, 200)).toEqual({
      paidPaise: 1_000_000,
      directPaise: 80_000,
      savePaise: 920_000,
    });
  });
});

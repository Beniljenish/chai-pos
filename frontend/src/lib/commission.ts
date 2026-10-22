/**
 * What delivery apps cost, against taking the same orders directly (README, "9.17").
 * Integer paise throughout; percentages are typed with up to two decimals and kept as basis points.
 */

/** "25" -> 2500, "2.5" -> 250; null when it is not a percentage from 0 to 100. */
export function percentToBp(text: string): number | null {
  const t = text.trim().replace('%', '');
  if (!/^\d{1,3}(\.\d{1,2})?$/.test(t)) return null;
  const bp = Math.round(Number(t) * 100);
  return bp <= 10000 ? bp : null;
}

/** Half-up, like every rupee rule in the app. */
export const share = (paise: number, bp: number) => Math.floor((paise * bp * 2 + 10_000) / 20_000);

export interface CommissionResult {
  paidPaise: number;
  directPaise: number;
  savePaise: number;
}

export function commission(salesPaise: number, appBp: number, directBp: number): CommissionResult {
  const paidPaise = share(salesPaise, appBp);
  const directPaise = share(salesPaise, directBp);
  return { paidPaise, directPaise, savePaise: paidPaise - directPaise };
}

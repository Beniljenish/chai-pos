/**
 * Quantities as people say them. The server stores base units (ml, g, piece)
 * as exact decimals; here we only format and preview. The server's own
 * conversion is the one that counts.
 */

export type BaseUnit = 'ml' | 'g' | 'piece';

const BIG: Record<BaseUnit, [string, number] | null> = {
  ml: ['L', 1000],
  g: ['kg', 1000],
  piece: null,
};

function trim(n: number, maxDecimals: number): string {
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: maxDecimals }).format(n);
}

/** 1700 ml -> "1.7 L", 250 g -> "250 g", 17 piece -> "17 pcs", -300 ml -> "-300 ml" */
export function formatQty(value: string | number, unit: BaseUnit): string {
  const n = Number(value);
  if (unit === 'piece') return `${trim(n, 3)} pcs`;
  const big = BIG[unit];
  if (big && Math.abs(n) >= big[1]) return `${trim(n / big[1], 3)} ${big[0]}`;
  return `${trim(n, 3)} ${unit}`;
}

/** Signed, for ledger rows: "+2 L", "-150 ml". */
export function formatDelta(value: string | number, unit: BaseUnit): string {
  const n = Number(value);
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${formatQty(Math.abs(n), unit)}`;
}

export interface PackUnit {
  id: string;
  name: string;
  qty_in_base: string;
}

/** Preview of "3 packets + 200 ml" in base units, rounded like the server (3 dp). */
export function packsToBase(units: PackUnit[], counts: Record<string, number>, loose: number): number {
  const total = units.reduce((sum, u) => sum + (counts[u.id] ?? 0) * Number(u.qty_in_base), 0) + loose;
  return Math.round(total * 1000) / 1000;
}

/** What the API takes: only packs actually entered. */
export function packsPayload(counts: Record<string, number>) {
  return Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([pack_unit_id, n]) => ({ pack_unit_id, qty: String(n) }));
}

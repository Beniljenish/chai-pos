/** Stock level bars: pure helpers, tested in stockLevel.test.ts. Display only:
 * the numbers that count are the ledger's, these just draw them. */

export type Tone = 'bad' | 'near' | 'ok' | 'none';

export interface Level {
  tone: Tone;
  /** Bar fill, 0-100, against twice the reorder level (the tick sits at 50). */
  fillPct: number;
  /** Where the reorder tick sits, 0-100; null with no reorder level. */
  tickPct: number | null;
}

/** Below the reorder level is "bad", up to a quarter above it "near", else "ok".
 * No reorder level (or below zero stock) draws no bar for "none", an empty bar for negatives. */
export function stockLevel(onHand: string | number, reorder: string | number | null | undefined): Level {
  const have = Number(onHand);
  const at = reorder === null || reorder === undefined ? NaN : Number(reorder);
  if (!Number.isFinite(at) || at <= 0) return { tone: 'none', fillPct: 0, tickPct: null };
  const fill = Math.max(0, Math.min(100, Math.round((have / (at * 2)) * 100)));
  const tone: Tone = have < at ? 'bad' : have < at * 1.25 ? 'near' : 'ok';
  return { tone, fillPct: fill, tickPct: 50 };
}

const ORDER: Record<Tone, number> = { bad: 0, near: 1, ok: 2, none: 3 };

/** Worst first: bad, near, ok, then items with no reorder level; ties by how far
 * below the tick, then name. */
export function worstFirst<T extends { name: string; level: Level }>(rows: T[]): T[] {
  return [...rows].sort(
    (a, b) =>
      ORDER[a.level.tone] - ORDER[b.level.tone] || a.level.fillPct - b.level.fillPct || a.name.localeCompare(b.name),
  );
}

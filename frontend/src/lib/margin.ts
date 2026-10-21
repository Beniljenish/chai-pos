/** Margin per item on the Margin screen: pure helpers, tested in margin.test.ts. */
import type { MarginItem } from './types';

export type MarginTone = 'bad' | 'near' | 'ok' | 'none';

/** Under half kept is pink, up to two thirds amber, above that green. An item with
 * no margin (no recipe, or an ingredient with no price yet) has no colour. */
export function marginTone(pct: number | null): MarginTone {
  if (pct === null) return 'none';
  return pct < 50 ? 'bad' : pct < 67 ? 'near' : 'ok';
}

export type MarginSort = 'worst' | 'best' | 'sales';

/** Items we cannot cost always go last, so they are not mistaken for the best or the worst. */
export function sortMargins(items: MarginItem[], how: MarginSort): MarginItem[] {
  const costed = items.filter((i) => i.margin_pct !== null);
  const rest = items.filter((i) => i.margin_pct === null).sort((a, b) => a.name.localeCompare(b.name));
  const by: Record<MarginSort, (a: MarginItem, b: MarginItem) => number> = {
    worst: (a, b) => (a.margin_pct as number) - (b.margin_pct as number),
    best: (a, b) => (b.margin_pct as number) - (a.margin_pct as number),
    sales: (a, b) => b.sold_28d - a.sold_28d,
  };
  return [...costed.sort((a, b) => by[how](a, b) || a.name.localeCompare(b.name)), ...rest];
}

/** What to tell the owner about an item that has no margin yet. */
export function whyNoMargin(i: MarginItem): string {
  if (i.status === 'no_recipe') return 'No recipe yet, so the cost is unknown';
  return `Add a price for ${i.missing.join(', ')} (enter it with a stock-in)`;
}

/**
 * Options on the bill (Large, Less sugar, Extra ginger): pure helpers for the
 * owner's editor, tested in options.test.ts.
 *
 * Phone number pads often have no minus key, so every signed amount is edited as
 * a direction (more / less) plus a plain number.
 */
import { formatRupees } from './gst';
import { formatQty, type BaseUnit } from './qty';
import type { Ingredient, Modifier, RecipeLine } from './types';

export type Dir = 'more' | 'less';

export interface OptionLine {
  key: string;
  ingredient_id: string;
  dir: Dir;
  qty: string;
}

export interface OptionDraft {
  name: string;
  priceDir: Dir;
  price: string; // rupees, unsigned
  scale: string; // 1 = same size
  lines: OptionLine[];
  is_active: boolean;
}

export const blankOption = (): OptionDraft => ({
  name: '',
  priceDir: 'more',
  price: '',
  scale: '1',
  lines: [],
  is_active: true,
});

const num = (s: string) => (s.trim() === '' ? NaN : Number(s));
const tidy = (n: number) => String(Math.round(n * 1000) / 1000);

export function toDraft(m: Modifier): OptionDraft {
  return {
    name: m.name,
    priceDir: m.price_delta_paise < 0 ? 'less' : 'more',
    price: m.price_delta_paise ? tidy(Math.abs(m.price_delta_paise) / 100) : '',
    scale: tidy(Number(m.scale_factor)),
    lines: m.lines.map((l) => ({
      key: l.ingredient_id,
      ingredient_id: l.ingredient_id,
      dir: Number(l.qty_delta) < 0 ? 'less' : 'more',
      qty: tidy(Math.abs(Number(l.qty_delta))),
    })),
    is_active: m.is_active,
  };
}

export function pricePaise(d: OptionDraft): number {
  const p = d.price.trim() === '' ? 0 : Math.round(num(d.price) * 100);
  return d.priceDir === 'less' ? -p : p;
}

/** What is wrong with the draft, in plain words, or null when it can be saved. */
export function validateOption(d: OptionDraft): string | null {
  if (!d.name.trim()) return 'Give the option a name, like "Large" or "Less sugar".';
  if (d.price.trim() !== '' && !(num(d.price) >= 0)) return 'Enter the price change in rupees, or leave it empty.';
  if (Math.abs(pricePaise(d)) > 100_00) return 'The price change can be at most ₹100.';
  const s = num(d.scale);
  if (!(s > 0 && s <= 10)) return 'Size must be more than 0 and at most 10 (1 means same size).';
  if (d.lines.some((l) => !l.ingredient_id)) return 'Choose an ingredient on every row, or remove the empty row.';
  const ids = d.lines.map((l) => l.ingredient_id);
  if (new Set(ids).size !== ids.length) return 'Each ingredient can appear only once.';
  if (d.lines.some((l) => !(num(l.qty) > 0))) return 'Every ingredient change must be more than zero.';
  return null;
}

/** Body for POST /modifiers or PATCH /modifiers/{id}. */
export function toOptionPayload(d: OptionDraft) {
  return {
    name: d.name.trim(),
    price_delta_paise: pricePaise(d),
    scale_factor: tidy(num(d.scale)),
    lines: d.lines.map((l) => ({
      ingredient_id: l.ingredient_id,
      qty_delta: (l.dir === 'less' ? '-' : '') + tidy(num(l.qty)),
    })),
  };
}

/** "+₹10" / "−₹5" / "" for no change. */
export function formatPriceDelta(paise: number): string {
  if (!paise) return '';
  return (paise < 0 ? '−' : '+') + formatRupees(Math.abs(paise));
}

/** One line for the list: "+₹10 · 1.5× size · Sugar +2 g". */
export function describeOption(m: Modifier, byId: Record<string, Ingredient | undefined>): string {
  const parts: string[] = [];
  const price = formatPriceDelta(m.price_delta_paise);
  if (price) parts.push(price);
  const scale = Number(m.scale_factor);
  if (scale !== 1) parts.push(`${tidy(scale)}× size`);
  for (const l of m.lines) {
    const ing = byId[l.ingredient_id];
    const q = Number(l.qty_delta);
    if (!ing || !q) continue;
    parts.push(`${ing.name} ${q < 0 ? '−' : '+'}${formatQty(Math.abs(q), ing.base_unit)}`);
  }
  return parts.length ? parts.join(' · ') : 'No change to price or stock';
}

export interface PreviewRow {
  name: string;
  unit: BaseUnit;
  before: number;
  after: number;
}

/**
 * One serving of a drink with this option, ingredient by ingredient. Same rule
 * as the server (services/billing.consumption_for_line): the recipe scales by the
 * size, except ingredients that do not grow with size (cups); then the option's
 * own changes are added; nothing goes below zero.
 */
export function previewServing(
  recipe: RecipeLine[],
  d: OptionDraft,
  byId: Record<string, Ingredient | undefined>,
): PreviewRow[] {
  const scale = num(d.scale) > 0 ? num(d.scale) : 1;
  const rows = new Map<string, PreviewRow>();
  for (const l of recipe) {
    const ing = byId[l.ingredient_id];
    const q = Number(l.qty);
    const fixed = ing ? !ing.scales_with_size : false;
    rows.set(l.ingredient_id, {
      name: l.ingredient_name,
      unit: l.base_unit as BaseUnit,
      before: q,
      after: fixed ? q : q * scale,
    });
  }
  for (const l of d.lines) {
    const ing = byId[l.ingredient_id];
    const q = num(l.qty);
    if (!ing || !(q > 0)) continue;
    const row = rows.get(l.ingredient_id) ?? { name: ing.name, unit: ing.base_unit, before: 0, after: 0 };
    row.after += l.dir === 'less' ? -q : q;
    rows.set(l.ingredient_id, row);
  }
  return [...rows.values()].map((r) => ({
    ...r,
    after: Math.max(0, Math.round(r.after * 1000) / 1000),
  }));
}

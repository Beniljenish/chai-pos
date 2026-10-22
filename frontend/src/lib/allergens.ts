/** Allergy tags and spice on dishes (README, "9.21"). The list is fixed so a filter means the same
 * on every outlet's menu; a tag is the outlet's statement, not a guarantee. */
import { t } from './i18n';

export const ALLERGENS = ['nuts', 'milk', 'gluten', 'egg', 'soy', 'fish', 'shellfish', 'sesame'] as const;
export type Allergen = (typeof ALLERGENS)[number];

export const allergenLabel = (a: string): string => t(a.charAt(0).toUpperCase() + a.slice(1));

/** Dishes left after hiding every one that carries any tag in `avoid`. */
export function withoutAllergens<T extends { allergens?: string[] }>(items: T[], avoid: string[]): T[] {
  if (avoid.length === 0) return items;
  return items.filter((i) => !(i.allergens ?? []).some((a) => avoid.includes(a)));
}

export const SPICE = ['Not spicy', 'Mild', 'Medium', 'Hot'] as const;
export const spiceLabel = (level: number | null | undefined): string | null =>
  level === null || level === undefined || level < 0 || level > 3 ? null : t(SPICE[level]);

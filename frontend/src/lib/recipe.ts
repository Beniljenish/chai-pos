/** Pure helpers for the recipe editor (tested in recipe.test.ts). */
import type { Recipe } from './types';

export interface EditLine {
  key: string;
  ingredient_id: string;
  qty: string;
}

export interface JuiceInputs {
  ingredient_id: string;
  ml_per_kg: string;
  portion_ml: string;
}

/** Same formula as the server: grams of fruit for one glass. */
export function fruitGramsPerPortion(mlPerKg: number, portionMl: number): number | null {
  if (!(mlPerKg > 0) || !(portionMl > 0)) return null;
  return Math.round((portionMl / mlPerKg) * 1000 * 1000) / 1000;
}

/** Split a saved recipe into editable lines and juice inputs. The fruit line of a
 * juice recipe is derived by the server, so it is edited through the yield, not as a line. */
export function toEditable(recipe: Recipe | null): { lines: EditLine[]; juice: JuiceInputs | null } {
  if (!recipe) return { lines: [], juice: null };
  const fruit = recipe.yield_inputs?.ingredient_id ?? null;
  return {
    lines: recipe.lines
      .filter((l) => l.ingredient_id !== fruit)
      .map((l) => ({ key: l.ingredient_id, ingredient_id: l.ingredient_id, qty: String(Number(l.qty)) })),
    juice: recipe.yield_inputs
      ? {
          ingredient_id: recipe.yield_inputs.ingredient_id,
          ml_per_kg: String(Number(recipe.yield_inputs.ml_per_kg)),
          portion_ml: String(Number(recipe.yield_inputs.portion_ml)),
        }
      : null,
  };
}

/** What is wrong with the draft, in plain words, or null when it can be saved. */
export function validate(lines: EditLine[], juice: JuiceInputs | null, yieldQty: string | null): string | null {
  if (lines.some((l) => !l.ingredient_id)) return 'Choose an ingredient on every row, or remove the empty row.';
  const used = lines.map((l) => l.ingredient_id);
  if (juice) used.push(juice.ingredient_id);
  if (used.length === 0) return 'Add at least one ingredient.';
  if (new Set(used).size !== used.length) return 'Each ingredient can appear only once.';
  if (lines.some((l) => !(Number(l.qty) > 0))) return 'Every quantity must be more than zero.';
  if (juice && fruitGramsPerPortion(Number(juice.ml_per_kg), Number(juice.portion_ml)) === null)
    return 'Enter how much juice 1 kg of fruit gives, and the glass size.';
  if (yieldQty !== null && !(Number(yieldQty) > 0)) return 'Enter how much one batch makes.';
  return null;
}

/** Body for PUT .../recipe. */
export function toPayload(lines: EditLine[], juice: JuiceInputs | null, yieldQty: string | null) {
  const body: Record<string, unknown> = {
    lines: lines.map((l) => ({ ingredient_id: l.ingredient_id, qty: String(Number(l.qty)) })),
  };
  if (juice)
    body.juice_yield = {
      ingredient_id: juice.ingredient_id,
      ml_per_kg: String(Number(juice.ml_per_kg)),
      portion_ml: String(Number(juice.portion_ml)),
    };
  if (yieldQty !== null) body.yield_qty = String(Number(yieldQty));
  return body;
}

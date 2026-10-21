/** What the AI routes return (README, "9.16"), and the checks the screens make before saving. */

export interface AiStatus {
  on: boolean;
  pretend: boolean;
  used_today: number;
  daily_limit: number;
}

export interface DraftLine {
  heard_name: string;
  ingredient_id: string | null;
  ingredient_name: string;
  base_unit: string;
  base_qty: string | null;
  cost_paise: number;
  problems: string[];
}

export interface Draft {
  supplier: string;
  lines: DraftLine[];
  lines_total_paise: number;
  bill_total_paise: number | null;
  total_matches: boolean | null;
}

/** A line is ready to save when it names a stock item, has a quantity and has a price. */
export const lineReady = (l: DraftLine): boolean => l.ingredient_id !== null && l.base_qty !== null && Number(l.base_qty) > 0 && l.cost_paise > 0;

/** "20000.000" ml -> "20 L"; grams -> kg; pieces stay. Only for showing, never for saving. */
export function showQty(unit: string, qty: string | null): string {
  if (qty === null) return '–';
  const n = Number(qty);
  const [label, factor] = unit === 'ml' ? ['L', 1000] : unit === 'g' ? ['kg', 1000] : ['pcs', 1];
  return `${Number((n / (factor as number)).toFixed(3))} ${label}`;
}

/** Re-scale a line when the owner corrects the quantity or the price, so nothing else drifts. */
export function withQty(l: DraftLine, text: string): DraftLine {
  const n = Number(text);
  const ok = text.trim() !== '' && Number.isFinite(n) && n > 0;
  return { ...l, base_qty: ok ? String(n) : null, problems: l.problems.filter((p) => !/quantity|counted in/i.test(p)) };
}

export function withCost(l: DraftLine, paise: number): DraftLine {
  return { ...l, cost_paise: paise, problems: paise > 0 ? l.problems.filter((p) => !/price/i.test(p)) : l.problems };
}

export function withIngredient(l: DraftLine, id: string | null, name: string, unit: string): DraftLine {
  return {
    ...l,
    ingredient_id: id,
    ingredient_name: name,
    base_unit: unit,
    problems: l.problems.filter((p) => !/stock item|counted in/i.test(p)),
  };
}

/** The sum a draft adds up to, to show next to the bill's own total. */
export const draftTotal = (lines: DraftLine[]): number => lines.reduce((a, l) => a + l.cost_paise, 0);

export interface AskAnswer {
  report: string;
  from: string;
  to: string;
  lines: string[];
  answer: string;
}

export interface DayExplain {
  date: string;
  language: string;
  facts: { id: string; kind: string; text: string; amount_paise?: number; bill_id?: string }[];
  summary: string;
  reasons: { fact_id: string; text: string }[];
}

export interface TranslateOut {
  name_ta: string;
  description_ta: string;
}

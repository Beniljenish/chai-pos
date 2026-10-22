/** Order together (README, "9.21"): pure helpers. */
import type { Cart, Carts } from './foodcourt';
import { changeOutletLine } from './foodcourt';
import type { GroupState } from './publicApi';

export type GroupLine = { outlet_id: string; menu_item_id: string; modifier_ids: string[]; qty: number };

/** This phone's carts as the lines it shares with the group. */
export function linesOf(carts: Carts): GroupLine[] {
  return Object.entries(carts).flatMap(([outlet, cart]: [string, Cart]) =>
    Object.values(cart).map((l) => ({ outlet_id: outlet, menu_item_id: l.itemId, modifier_ids: l.mods, qty: l.qty })),
  );
}

/** A signature that changes only when the shared lines change (so an unchanged cart sends nothing). */
export const signature = (lines: GroupLine[]): string =>
  JSON.stringify(
    [...lines]
      .map((l) => [l.outlet_id, l.menu_item_id, [...l.modifier_ids].sort(), l.qty])
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))),
  );

/** The host's carts with everyone else's dishes added (their own are already in them). */
export function withOthers(carts: Carts, state: GroupState): Carts {
  return state.lines
    .filter((l) => !l.mine)
    .reduce((c, l) => changeOutletLine(c, l.outlet_id, l.menu_item_id, l.modifier_ids, l.qty), carts);
}

/** The group token in a link (`?group=...`): letters, digits, dash and underscore only. */
export function groupFromSearch(search: string): string | null {
  const g = new URLSearchParams(search).get('group') ?? '';
  return /^[A-Za-z0-9_-]{6,16}$/.test(g) ? g : null;
}

export const groupLink = (origin: string, slug: string, token: string): string =>
  `${origin}/order/${encodeURIComponent(slug)}?group=${encodeURIComponent(token)}`;

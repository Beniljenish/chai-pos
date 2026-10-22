import { describe, expect, it } from 'vitest';
import { groupFromSearch, groupLink, linesOf, signature, withOthers } from './group';
import type { GroupState } from './publicApi';

describe('order together', () => {
  const carts = { o1: { 'tea': { itemId: 'tea', qty: 2, mods: [] }, 'juice|x': { itemId: 'juice', qty: 1, mods: ['x'] } } };

  it('shares this phone\'s carts as lines', () => {
    expect(linesOf(carts)).toEqual([
      { outlet_id: 'o1', menu_item_id: 'tea', modifier_ids: [], qty: 2 },
      { outlet_id: 'o1', menu_item_id: 'juice', modifier_ids: ['x'], qty: 1 },
    ]);
  });

  it('has a signature that ignores order but not content', () => {
    const a = linesOf(carts);
    expect(signature(a)).toBe(signature([...a].reverse()));
    expect(signature(a)).not.toBe(signature([{ ...a[0], qty: 3 }, a[1]]));
  });

  it('adds only other people\'s dishes to the host\'s carts', () => {
    const state = {
      lines: [
        { member: 'Me', mine: true, outlet_id: 'o1', menu_item_id: 'tea', modifier_ids: [], qty: 2 },
        { member: 'Ravi', mine: false, outlet_id: 'o1', menu_item_id: 'tea', modifier_ids: [], qty: 1 },
        { member: 'Meena', mine: false, outlet_id: 'o2', menu_item_id: 'roll', modifier_ids: [], qty: 2 },
      ],
    } as unknown as GroupState;
    const merged = withOthers(carts, state);
    expect(merged.o1.tea.qty).toBe(3); // 2 of mine + 1 of Ravi's
    expect(merged.o1['juice|x'].qty).toBe(1);
    expect(merged.o2.roll.qty).toBe(2);
  });

  it('reads a group token from a link and refuses odd ones', () => {
    expect(groupFromSearch('?group=AbC-123_xYz')).toBe('AbC-123_xYz');
    expect(groupFromSearch('?group=short')).toBeNull();
    expect(groupFromSearch('?group=<script>alert(1)</script>')).toBeNull();
    expect(groupFromSearch('')).toBeNull();
    expect(groupLink('https://app.example', 'marina', 'tok_123456')).toBe('https://app.example/order/marina?group=tok_123456');
  });
});

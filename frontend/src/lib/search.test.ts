import { describe, expect, it } from 'vitest';
import { highlightParts, searchItems } from './search';

const menu = [
  { name: 'Badam milk', category: 'Coffee' },
  { name: 'Banana shake', category: 'Juice' },
  { name: 'Filter coffee', category: 'Coffee' },
  { name: 'Bajji', category: 'Snacks' },
];

describe('searchItems', () => {
  it('keeps everything for an empty search', () => {
    expect(searchItems(menu, '  ')).toHaveLength(4);
  });
  it('matches the name in any category, ignoring case', () => {
    expect(searchItems(menu, 'BA').map((i) => i.name)).toEqual(['Badam milk', 'Banana shake', 'Bajji']);
  });
  it('needs every word, in any order, and also matches the category', () => {
    expect(searchItems(menu, 'milk badam')).toHaveLength(1);
    expect(searchItems(menu, 'coffee filter')).toHaveLength(1);
    expect(searchItems(menu, 'juice')).toHaveLength(1);
    expect(searchItems(menu, 'zzz')).toEqual([]);
  });
});

describe('highlightParts', () => {
  it('marks the typed letters', () => {
    expect(highlightParts('Badam milk', 'ba')).toEqual([
      { text: 'Ba', hit: true },
      { text: 'dam milk', hit: false },
    ]);
  });
  it('marks every word, wherever it falls', () => {
    expect(highlightParts('Badam milk', 'milk ad')).toEqual([
      { text: 'B', hit: false },
      { text: 'ad', hit: true },
      { text: 'am ', hit: false },
      { text: 'milk', hit: true },
    ]);
  });
  it('is one plain run with no search', () => {
    expect(highlightParts('Bajji', '')).toEqual([{ text: 'Bajji', hit: false }]);
  });
});

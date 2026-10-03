import { expect, it } from 'vitest';
import { nextNames } from './floor';

it('continues the table series and skips names already used anywhere', () => {
  expect(nextNames([], 3, 'T')).toEqual(['T1', 'T2', 'T3']);
  expect(nextNames(['T1', 't2', 'T4'], 3, 'T')).toEqual(['T3', 'T5', 'T6']);
  expect(nextNames(['P1'], 2, 'P')).toEqual(['P2', 'P3']);
  expect(nextNames(['T1'], 0, 'T')).toEqual([]);
});

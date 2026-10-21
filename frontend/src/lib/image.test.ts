import { describe, expect, it } from 'vitest';
import { fitSize } from './image';

describe('fitSize', () => {
  it('leaves a small picture alone', () => {
    expect(fitSize(800, 600)).toEqual({ w: 800, h: 600 });
  });
  it('shrinks the long side to 1600 and keeps the shape', () => {
    expect(fitSize(4000, 3000)).toEqual({ w: 1600, h: 1200 });
    expect(fitSize(3000, 4000)).toEqual({ w: 1200, h: 1600 });
  });
});

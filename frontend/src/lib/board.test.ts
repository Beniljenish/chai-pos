import { describe, expect, it } from 'vitest';
import { calls, newlyReady } from './board';

describe('display board calls', () => {
  it('calls only what turned ready since the last look', () => {
    expect(newlyReady(['JT-1'], ['JT-1', 'AB-4'])).toEqual(['AB-4']);
    expect(newlyReady(['JT-1'], [])).toEqual([]);
  });

  it('says nothing at the very first look', () => {
    expect(newlyReady(null, ['JT-1', 'JT-2'])).toEqual([]);
  });

  it('says a token in English and in Tamil', () => {
    expect(calls('JT-17', ['en', 'ta'])).toEqual([
      { lang: 'en', text: 'Token JT 17 is ready' },
      { lang: 'ta', text: 'டோக்கன் JT 17 தயார்' },
    ]);
  });
});

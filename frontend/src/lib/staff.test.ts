import { describe, expect, it } from 'vitest';
import { firstPassword, formatPhone, passwordProblem } from './staff';

describe('password rules (same as the server)', () => {
  it.each([
    ['short1', 'at least 8'],
    ['12345678', 'too easy'],
    ['aaaaaaaa', 'too easy'],
    ['ababababab', 'too easy'],
    ['me9876500001', 'phone number'],
  ])('refuses %s', (pw, words) => {
    expect(passwordProblem(pw, '9876500001')).toContain(words);
  });
  it('accepts an ordinary password', () => {
    expect(passwordProblem('masala-tea-77', '9876500001')).toBeNull();
  });
});

describe('first passwords', () => {
  it('are a word and four digits, and pass the rules', () => {
    const fixed = firstPassword(() => 0);
    expect(fixed).toBe('ginger1000');
    for (let i = 0; i < 50; i++) {
      const p = firstPassword();
      expect(p).toMatch(/^[a-z]+\d{4}$/);
      expect(passwordProblem(p, '9876500001')).toBeNull();
    }
  });
});

it('formats phone numbers the way people say them', () => {
  expect(formatPhone('9876500001')).toBe('98765 00001');
});

import { afterEach, describe, expect, it, vi } from 'vitest';
import { dishDescription, dishName, fill, getLang, setLang, t } from './i18n';
import { TA } from './ta';

// The tests run in plain Node: give them a tiny in-memory localStorage and document.
const mem = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => mem.get(k) ?? null,
  setItem: (k: string, v: string) => void mem.set(k, v),
  removeItem: (k: string) => void mem.delete(k),
  clear: () => mem.clear(),
});
vi.stubGlobal('document', { documentElement: { lang: 'en' } });

afterEach(() => {
  setLang('en');
  localStorage.clear();
});

describe('t()', () => {
  it('gives the English text itself in English', () => {
    expect(t('Add to cart · {price}', { price: '₹20' })).toBe('Add to cart · ₹20');
  });

  it('gives Tamil when chosen, with the values moved to where Tamil puts them', () => {
    setLang('ta');
    expect(t('Add to cart · {price}', { price: '₹20' })).toBe('கார்ட்டில் சேர் · ₹20');
    expect(t('{open} of {outlets} open', { open: 2, outlets: 5 })).toBe('5 கடைகளில் 2 திறந்துள்ளன');
  });

  it('shows English, not a blank, for text with no Tamil yet', () => {
    setLang('ta');
    expect(t('A sentence nobody has translated yet')).toBe('A sentence nobody has translated yet');
  });

  it('leaves an unknown {name} alone instead of printing "undefined"', () => {
    expect(fill('Hello {who} {missing}', { who: 'Ravi' })).toBe('Hello Ravi {missing}');
  });

  it('remembers the choice on the device', () => {
    setLang('ta');
    expect(localStorage.getItem('taptallow.lang')).toBe('ta');
    expect(getLang()).toBe('ta');
    expect(document.documentElement.lang).toBe('ta');
  });
});

describe('dish names', () => {
  const tea = { name: 'Masala tea', name_ta: 'மசாலா டீ', description: 'Strong', description_ta: 'கடுமையான' };

  it('use the outlet’s Tamil only when Tamil is chosen and it was written', () => {
    expect(dishName(tea)).toBe('Masala tea');
    setLang('ta');
    expect(dishName(tea)).toBe('மசாலா டீ');
    expect(dishDescription(tea)).toBe('கடுமையான');
    expect(dishName({ name: 'Juice', name_ta: '' })).toBe('Juice');
    expect(dishDescription({ description: 'Fresh' })).toBe('Fresh');
  });
});

describe('the Tamil dictionary', () => {
  it('has Tamil for every entry and keeps {values} the same as the English', () => {
    for (const [en, ta] of Object.entries(TA)) {
      expect(ta.trim(), en).not.toBe('');
      const vars = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join(',');
      expect(vars(ta), `values in "${en}"`).toBe(vars(en));
    }
  });
});

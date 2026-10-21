import { afterEach, describe, expect, it, vi } from 'vitest';
import { DEFAULTS, loadSettings, phrase, saveSettings, spokenAmount, spokenToken } from './announce';

// The tests run in plain Node: give them a tiny in-memory localStorage and document.
const mem = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => mem.get(k) ?? null,
  setItem: (k: string, v: string) => void mem.set(k, v),
  removeItem: (k: string) => void mem.delete(k),
  clear: () => mem.clear(),
});
vi.stubGlobal('document', { documentElement: { lang: 'en' } });

afterEach(() => localStorage.clear());

describe('what is said aloud', () => {
  it('reads a token without the hyphen', () => {
    expect(spokenToken('JT-17')).toBe('JT 17');
  });

  it('says rupees and paise in both languages', () => {
    expect(spokenAmount(6000, 'en')).toBe('60 rupees');
    expect(spokenAmount(6050, 'en')).toBe('60 rupees 50 paise');
    expect(spokenAmount(6000, 'ta')).toBe('60 ரூபாய்');
    expect(spokenAmount(6050, 'ta')).toBe('60 ரூபாய் 50 பைசா');
  });

  it('builds each sentence in English and Tamil', () => {
    expect(phrase('ready', 'en', { token: 'JT-17' })).toBe('Token JT 17 is ready');
    expect(phrase('ready', 'ta', { token: 'JT-17' })).toBe('டோக்கன் JT 17 தயார்');
    expect(phrase('paid', 'en', { paise: 6000 })).toBe('60 rupees received');
    expect(phrase('paid', 'ta', { paise: 6000 })).toBe('60 ரூபாய் வரப்பெற்றது');
    expect(phrase('order', 'en', { token: 'JT-3' })).toBe('New online order. Token JT 3');
    expect(phrase('order', 'ta', { token: 'JT-3' })).toContain('JT 3');
  });
});

describe('the tablet remembers its choice', () => {
  it('starts switched off', () => {
    expect(loadSettings()).toEqual(DEFAULTS);
    expect(DEFAULTS.on).toBe(false);
  });

  it('keeps what was saved, and survives a damaged value', () => {
    saveSettings({ on: true, ready: true, paid: false, order: true, volume: 0.5 });
    expect(loadSettings()).toMatchObject({ on: true, paid: false, volume: 0.5 });
    localStorage.setItem('taptallow.announce', '{not json');
    expect(loadSettings()).toEqual(DEFAULTS);
    localStorage.setItem('taptallow.announce', JSON.stringify({ on: true, volume: 9 }));
    expect(loadSettings().volume).toBe(1);
  });
});

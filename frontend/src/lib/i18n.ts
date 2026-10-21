/**
 * Tamil and English (README, "9.16").
 *
 * The English text IS the key: `t("Add to cart")` gives the Tamil from `ta.ts` when the person
 * picked Tamil, and the English itself when there is no Tamil for it. So a missing translation
 * shows English, never a blank or a raw key, and a new screen works before it is translated.
 * Variables are written `{name}` in both languages, because Tamil puts words in another order.
 *
 * The choice is kept on the device. Everything that calls `useLang()` re-renders when it changes.
 */
import { useSyncExternalStore } from 'react';
import { TA } from './ta';

export type Lang = 'en' | 'ta';
export const LANG_KEY = 'taptallow.lang';

function read(): Lang {
  try {
    const v = localStorage.getItem(LANG_KEY);
    if (v === 'ta' || v === 'en') return v;
  } catch {
    /* private window or blocked storage: stay on English */
  }
  return 'en';
}

let current: Lang = read();
if (typeof document !== 'undefined') document.documentElement.lang = current; // screen readers and fonts follow
const listeners = new Set<() => void>();

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  current = lang;
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* the choice just will not be remembered */
  }
  if (typeof document !== 'undefined') document.documentElement.lang = lang;
  listeners.forEach((f) => f());
}

function subscribe(f: () => void): () => void {
  listeners.add(f);
  return () => listeners.delete(f);
}

/** Re-renders the component when the language changes. Call it once near the top of a screen. */
export function useLang(): Lang {
  return useSyncExternalStore(subscribe, getLang, () => 'en');
}

export type Vars = Record<string, string | number>;

export function fill(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, k: string) => (k in vars ? String(vars[k]) : whole));
}

/** The text in the chosen language, with {name} filled in. */
export function t(text: string, vars?: Vars): string {
  const found = current === 'ta' ? TA[text] : undefined;
  return fill(found ?? text, vars);
}

/** A dish's name for the customer: the Tamil one when Tamil is chosen and the outlet wrote it. */
export function dishName(item: { name: string; name_ta?: string }): string {
  return current === 'ta' && item.name_ta ? item.name_ta : item.name;
}

export function dishDescription(item: { description?: string; description_ta?: string }): string {
  return (current === 'ta' && item.description_ta ? item.description_ta : item.description) ?? '';
}

/** English or Tamil number words in a sentence are left alone: numbers stay 0-9 on purpose. */
export const LANGUAGES: { id: Lang; label: string }[] = [
  { id: 'ta', label: 'தமிழ்' },
  { id: 'en', label: 'English' },
];

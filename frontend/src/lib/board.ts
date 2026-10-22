/** The food court's display board: which tokens to call out loud (README, "9.17"). */
import { phrase } from './announce';
import type { Lang } from './i18n';

/** Tokens that are ready now and were not before. The first look at the board calls nothing:
 * a screen switched on at noon should not shout every token that has been waiting. */
export function newlyReady(before: string[] | null, now: string[]): string[] {
  if (before === null) return [];
  const had = new Set(before);
  return now.filter((t) => !had.has(t));
}

/** What the board says for a token, in each language it can speak. */
export const calls = (token: string, langs: Lang[]): { lang: Lang; text: string }[] =>
  langs.map((lang) => ({ lang, text: phrase('ready', lang, { token }) }));

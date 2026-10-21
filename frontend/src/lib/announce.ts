/**
 * Speaking tokens and payments aloud (README, "9.16"): "Token JT 17 is ready", "₹60 received".
 *
 * Counter staff and customers often cannot read the screen but can always hear it, the way a
 * UPI soundbox works. Off until someone switches it on (a shop may not want a talking till), and
 * the choice is kept on that tablet. If the tablet has no Tamil voice, the line is said in
 * English instead of being said badly or not at all.
 */
import { getLang, type Lang, type Vars, fill } from './i18n';
import { hasVoice, speak } from './voice';

export type Kind = 'ready' | 'paid' | 'order';

export interface AnnounceSettings {
  on: boolean;
  ready: boolean;
  paid: boolean;
  order: boolean;
  volume: number;
}

const KEY = 'taptallow.announce';
export const DEFAULTS: AnnounceSettings = { on: false, ready: true, paid: true, order: true, volume: 1 };

const LINES: Record<Lang, Record<Kind, string>> = {
  en: {
    ready: 'Token {token} is ready',
    paid: '{amount} received',
    order: 'New online order. Token {token}',
  },
  ta: {
    ready: 'டோக்கன் {token} தயார்',
    paid: '{amount} வரப்பெற்றது',
    order: 'புதிய ஆன்லைன் ஆர்டர். டோக்கன் {token}',
  },
};

/** "JT-17" is read out as "JT 17", not "J T minus 17". */
export const spokenToken = (token: string): string => token.replace(/-/g, ' ');

/** 6050 paise -> "60 rupees 50 paise" / "60 ரூபாய் 50 பைசா". */
export function spokenAmount(paise: number, lang: Lang): string {
  const rupees = Math.floor(paise / 100);
  const rest = paise % 100;
  const [r, p] = lang === 'ta' ? ['ரூபாய்', 'பைசா'] : ['rupees', 'paise'];
  return rest === 0 ? `${rupees} ${r}` : `${rupees} ${r} ${rest} ${p}`;
}

/** The sentence for an event, in a language. Pure, so it is tested without a speaker. */
export function phrase(kind: Kind, lang: Lang, v: { token?: string; paise?: number }): string {
  const vars: Vars = {
    token: spokenToken(v.token ?? ''),
    amount: spokenAmount(v.paise ?? 0, lang),
  };
  return fill(LINES[lang][kind], vars);
}

export function loadSettings(): AnnounceSettings {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    if (raw && typeof raw === 'object') {
      const r = raw as Partial<AnnounceSettings>;
      return {
        on: r.on === true,
        ready: r.ready !== false,
        paid: r.paid !== false,
        order: r.order !== false,
        volume: typeof r.volume === 'number' ? Math.max(0, Math.min(1, r.volume)) : 1,
      };
    }
  } catch {
    /* blocked storage or a damaged value: the defaults */
  }
  return { ...DEFAULTS };
}

export function saveSettings(s: AnnounceSettings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* the choice just will not be remembered */
  }
}

/** Say it, if this tablet is set to. Returns whether anything was said. */
export function announce(kind: Kind, v: { token?: string; paise?: number }, settings = loadSettings()): boolean {
  if (!settings.on || !settings[kind]) return false;
  const wanted = getLang();
  const lang: Lang = wanted === 'ta' && !hasVoice('ta') ? 'en' : wanted;
  return speak(phrase(kind, lang, v), lang, settings.volume);
}

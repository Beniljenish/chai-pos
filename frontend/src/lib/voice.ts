/**
 * The phone's own speech, both ways (README, "9.16"): listening (speech to text, for "speak your
 * purchase" and "Ask your shop") and speaking (text to speech, for "Token 17 ready").
 *
 * Both are built into the browser, so there is no key and no cost. Neither is guaranteed:
 * Chrome on Android has Tamil for both, many desktops have no Tamil voice, and iPhone's browsers
 * differ. Every function says plainly when it cannot, so a screen can fall back to typing and an
 * announcement can fall back to English.
 */
import type { Lang } from './i18n';

export const speechLang = (lang: Lang): string => (lang === 'ta' ? 'ta-IN' : 'en-IN');

// ---- the parts of the Web Speech API we use (not in every TypeScript lib)
interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type RecognitionCtor = new () => Recognition;
type SpeechWindow = Window & { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as SpeechWindow;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const canListen = (): boolean => recognitionCtor() !== null;

export interface ListenHandlers {
  /** Called with everything heard so far (spoken text keeps being replaced as it firms up). */
  onText(text: string, final: boolean): void;
  onEnd(): void;
  /** `denied` (microphone refused), `none` (heard nothing), or `other`. */
  onError(kind: 'denied' | 'none' | 'other'): void;
}

/** Start listening; returns a function that stops. Call from a tap: browsers need that. */
export function listen(lang: Lang, h: ListenHandlers): () => void {
  const Ctor = recognitionCtor();
  if (!Ctor) {
    h.onError('other');
    h.onEnd();
    return () => undefined;
  }
  const r = new Ctor();
  r.lang = speechLang(lang);
  r.interimResults = true;
  r.continuous = false;
  r.onresult = (e) => {
    let text = '';
    let final = false;
    for (let i = 0; i < e.results.length; i++) {
      text += e.results[i][0].transcript;
      final = e.results[i].isFinal;
    }
    h.onText(text.trim(), final);
  };
  r.onerror = (e) => h.onError(e.error === 'not-allowed' || e.error === 'service-not-allowed' ? 'denied' : e.error === 'no-speech' ? 'none' : 'other');
  r.onend = () => h.onEnd();
  try {
    r.start();
  } catch {
    h.onError('other');
    h.onEnd();
  }
  return () => {
    try {
      r.stop();
    } catch {
      /* already stopped */
    }
  };
}

// ---- speaking
export const canSpeak = (): boolean => typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined';

/** Is there a voice for this language on this device? (Voices can load late: ask again later.) */
export function hasVoice(lang: Lang): boolean {
  if (!canSpeak()) return false;
  const want = speechLang(lang).slice(0, 2);
  return window.speechSynthesis.getVoices().some((v) => v.lang.toLowerCase().startsWith(want));
}

/** Say it aloud. Returns false when this device cannot speak at all. */
export function speak(text: string, lang: Lang, volume = 1): boolean {
  if (!canSpeak() || !text) return false;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = speechLang(lang);
  const want = u.lang.slice(0, 2);
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(want));
  if (voice) u.voice = voice;
  u.volume = Math.max(0, Math.min(1, volume));
  u.rate = 0.95;
  window.speechSynthesis.speak(u);
  return true;
}

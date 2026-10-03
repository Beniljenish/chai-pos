/**
 * Staff passwords: the same rules as the server (services/auth.password_problem),
 * so the screen can say what is wrong before sending. Tested in staff.test.ts.
 */

const TOO_COMMON = new Set([
  '12345678', '123456789', '1234567890', '87654321', '11111111', '00000000',
  'password', 'password1', 'qwertyui', 'abcd1234', 'chai1234', 'tea12345',
]);

export function passwordProblem(password: string, phone: string): string | null {
  if (password.length < 8) return 'Use at least 8 characters';
  const p = password.toLowerCase();
  if (TOO_COMMON.has(p) || new Set(p).size < 3) return 'That password is too easy to guess';
  if (phone && password.includes(phone)) return 'Do not use your phone number in the password';
  return null;
}

const WORDS = ['ginger', 'masala', 'tulsi', 'lemon', 'mango', 'elaichi', 'jaggery', 'mint', 'saffron', 'pepper'];

/** A first password the owner can read out: a word and four digits ("ginger4821").
 * Easy to say aloud; the person replaces it at first login anyway. */
export function firstPassword(random: (n: number) => number = cryptoRandom): string {
  const word = WORDS[random(WORDS.length)];
  const digits = String(random(9000) + 1000);
  return `${word}${digits}`;
}

function cryptoRandom(n: number): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] % n;
}

/** "9876500001" -> "98765 00001", the way people say Indian mobile numbers. */
export const formatPhone = (p: string) => (p.length === 10 ? `${p.slice(0, 5)} ${p.slice(5)}` : p);

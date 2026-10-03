/** GSTIN checks, mirroring backend/app/core/gstin.py (same test vectors in gstin.test.ts). */

const CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
const FORMAT = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export const STATES: Record<string, string> = {
  '01': 'Jammu & Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh', '05': 'Uttarakhand',
  '06': 'Haryana', '07': 'Delhi', '08': 'Rajasthan', '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim',
  '12': 'Arunachal Pradesh', '13': 'Nagaland', '14': 'Manipur', '15': 'Mizoram', '16': 'Tripura', '17': 'Meghalaya',
  '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand', '21': 'Odisha', '22': 'Chhattisgarh', '23': 'Madhya Pradesh',
  '24': 'Gujarat', '25': 'Daman & Diu', '26': 'Dadra & Nagar Haveli and Daman & Diu', '27': 'Maharashtra',
  '28': 'Andhra Pradesh (old)', '29': 'Karnataka', '30': 'Goa', '31': 'Lakshadweep', '32': 'Kerala',
  '33': 'Tamil Nadu', '34': 'Puducherry', '35': 'Andaman & Nicobar Islands', '36': 'Telangana', '37': 'Andhra Pradesh',
  '38': 'Ladakh', '97': 'Other territory', '99': 'Centre jurisdiction',
};

export function checkDigit(first14: string): string {
  let total = 0;
  for (let i = 0; i < 14; i++) {
    const product = CHARS.indexOf(first14[i]) * (i % 2 === 0 ? 1 : 2);
    total += Math.floor(product / 36) + (product % 36);
  }
  return CHARS[(36 - (total % 36)) % 36];
}

export type GstinCheck = { ok: true; gstin: string; state: string } | { ok: false; reason: string };

/** Same rules and reasons as the server, for instant feedback while typing. */
export function checkGstin(raw: string): GstinCheck {
  const g = raw.replace(/\s+/g, '').toUpperCase();
  if (g.length !== 15) return { ok: false, reason: `A GSTIN has 15 characters (${g.length} so far)` };
  if (!FORMAT.test(g)) return { ok: false, reason: 'That is not a GSTIN (expected like 33ABCDE1234F1Z7)' };
  if (!STATES[g.slice(0, 2)]) return { ok: false, reason: `${g.slice(0, 2)} is not an Indian state code` };
  if (checkDigit(g.slice(0, 14)) !== g[14])
    return { ok: false, reason: "The last character does not match; a character is probably mistyped" };
  return { ok: true, gstin: g, state: STATES[g.slice(0, 2)] };
}

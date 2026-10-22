/** An outlet's offers (README, "9.19"): the shapes the owner screen talks about, and plain wording. */
import { formatRupees } from './gst';
import { t } from './i18n';

export interface Offer {
  id: string;
  code: string;
  kind: 'percent' | 'amount';
  value: number; // a percentage, or paise
  min_order_paise: number;
  max_discount_paise: number | null;
  valid_until: string | null;
  max_uses: number | null;
  is_active: boolean;
  uses: number;
}

/** "10% off (up to ₹20)" / "₹10 off". */
export function offerText(o: Pick<Offer, 'kind' | 'value' | 'max_discount_paise' | 'min_order_paise'>): string {
  const base =
    o.kind === 'percent'
      ? t('{n}% off', { n: o.value }) +
        (o.max_discount_paise ? ` (${t('up to {amount}', { amount: formatRupees(o.max_discount_paise) })})` : '')
      : t('{amount} off', { amount: formatRupees(o.value) });
  return o.min_order_paise ? `${base} · ${t('on orders of {amount} or more', { amount: formatRupees(o.min_order_paise) })}` : base;
}

/** Whether an offer works today (the owner's list shows why not). */
export function offerState(o: Offer, today: string): 'on' | 'off' | 'expired' | 'used_up' {
  if (!o.is_active) return 'off';
  if (o.valid_until && o.valid_until < today) return 'expired';
  if (o.max_uses !== null && o.uses >= o.max_uses) return 'used_up';
  return 'on';
}

/** A typed code as the server keeps it: no spaces, capitals; null when it is not 3 to 20 letters/digits. */
export function cleanCode(text: string): string | null {
  const c = text.replace(/\s+/g, '').toUpperCase();
  return /^[A-Z0-9]{3,20}$/.test(c) ? c : null;
}

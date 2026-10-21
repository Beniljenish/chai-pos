/**
 * The till's Phase 6 sheets (README, "Phase 6"): a discount with a reason, a
 * split payment, and the customer (needed for credit). All work offline: the
 * customer is made on the tablet and the server keeps one per number.
 */
import { useEffect, useState } from 'react';
import { discountAllowed, percentOff, uuidv7 } from '../lib/billing';
import { formatRupees } from '../lib/gst';
import type { BillCustomer } from '../lib/types';
import { api } from './apiClient';
import { Sheet } from './Sheet';
import { t, useLang } from '../lib/i18n';

export const DISCOUNT_REASONS = ['Regular customer', 'Staff', 'Complaint', 'Offer'];

const toPaise = (rupees: string) => Math.round(Number(rupees || '0') * 100);
const rupeesOk = (v: string) => /^\d{0,6}(\.\d{0,2})?$/.test(v);

export interface DiscountTarget {
  key: string; // 'bill', or a cart line's key
  label: string;
  grossPaise: number; // what it is taken off
}

/** A discount on the whole bill or one line, in rupees or percent, with a reason. */
export function DiscountSheet({
  targets,
  current,
  reason: initialReason,
  billGrossPaise,
  otherDiscountPaise,
  maxBp,
  isOwner,
  onClose,
  onApply,
}: {
  targets: DiscountTarget[];
  current: Record<string, number>;
  reason: string;
  billGrossPaise: number;
  /** Discounts already on the bill elsewhere (other lines or the bill), for the limit. */
  otherDiscountPaise: (key: string) => number;
  maxBp: number;
  isOwner: boolean;
  onClose(): void;
  onApply(key: string, paise: number, reason: string): void;
}) {
  useLang();
  const [key, setKey] = useState(targets[0].key);
  const [unit, setUnit] = useState<'rs' | 'pct'>('rs');
  const [value, setValue] = useState(current[targets[0].key] ? String(current[targets[0].key] / 100) : '');
  const [reason, setReason] = useState(initialReason);
  const target = targets.find((t) => t.key === key) ?? targets[0];
  const paise = unit === 'rs' ? toPaise(value) : percentOff(Number(value || '0'), target.grossPaise);
  const tooBig = paise > target.grossPaise;
  const allowed = discountAllowed({
    discountPaise: paise + otherDiscountPaise(key),
    grossPaise: billGrossPaise,
    maxBp,
    isOwner,
  });
  const ok = !tooBig && allowed && (paise === 0 || reason.trim() !== '');

  return (
    <Sheet title={t("Discount")} onClose={onClose}>
      {targets.length > 1 && (
        <label>
          {t("Take it off")}
          <select
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setValue(current[e.target.value] ? String(current[e.target.value] / 100) : '');
            }}
          >
            {targets.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label} ({formatRupees(t.grossPaise)})
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="chips" role="group" aria-label={t("Discount in")}>
        <button className="chip" aria-pressed={unit === 'rs'} onClick={() => setUnit('rs')}>
          ₹
        </button>
        <button className="chip" aria-pressed={unit === 'pct'} onClick={() => setUnit('pct')}>
          %
        </button>
      </div>
      <label>
        {unit === 'rs' ? t("Amount off (₹)") : t("Percent off")}
        <input
          inputMode="decimal"
          value={value}
          autoFocus
          onChange={(e) => rupeesOk(e.target.value) && setValue(e.target.value)}
        />
      </label>
      {unit === 'pct' && paise > 0 && <p className="muted num">= {formatRupees(paise)} {t("off")}</p>}
      <p className="field-label">{t("Why")}</p>
      <div className="chips" role="group" aria-label={t("Reason")}>
        {DISCOUNT_REASONS.map((r) => (
          <button key={r} className="chip" aria-pressed={reason === r} onClick={() => setReason(r)}>
            {t(r)}
          </button>
        ))}
      </div>
      <label>
        {t("Or in your words")}
        <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} />
      </label>
      {tooBig && <p className="error">{t('More than {amount}.', { amount: formatRupees(target.grossPaise) })}</p>}
      {!allowed && (
        <p className="error" role="alert">
          {t('A cashier can take off up to {pct}% of the bill. Ask the owner.', { pct: maxBp / 100 })}
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" disabled={!ok} onClick={() => onApply(key, paise, reason.trim())}>
          {paise ? t('Take off {amount}', { amount: formatRupees(paise) }) : t('No discount')}
        </button>
        <button onClick={onClose}>{t("Cancel")}</button>
      </div>
    </Sheet>
  );
}

export interface SplitChoice {
  cashPaise: number;
  other: 'upi' | 'card';
}

/** Part in cash, the rest by UPI or card. */
export function SplitSheet({
  totalPaise,
  initial,
  onClose,
  onApply,
}: {
  totalPaise: number;
  initial: SplitChoice | null;
  onClose(): void;
  onApply(s: SplitChoice): void;
}) {
  useLang();
  const [cash, setCash] = useState(initial ? String(initial.cashPaise / 100) : '');
  const [other, setOther] = useState<'upi' | 'card'>(initial?.other ?? 'upi');
  const cashPaise = toPaise(cash);
  const rest = totalPaise - cashPaise;
  const ok = cashPaise > 0 && rest > 0;
  return (
    <Sheet title={`Split ${formatRupees(totalPaise)}`} onClose={onClose}>
      <label>
        {t("Cash (₹)")}
        <input inputMode="decimal" value={cash} autoFocus onChange={(e) => rupeesOk(e.target.value) && setCash(e.target.value)} />
      </label>
      <p className="field-label">{t("The rest by")}</p>
      <div className="chips" role="group" aria-label={t("The rest by")}>
        <button className="chip" aria-pressed={other === 'upi'} onClick={() => setOther('upi')}>
          {t("UPI")}
        </button>
        <button className="chip" aria-pressed={other === 'card'} onClick={() => setOther('card')}>
          {t("Card")}
        </button>
      </div>
      <p className="num" role="status">
        {ok ? t('Cash {cash} + {other} {rest}', { cash: formatRupees(cashPaise), other: other === 'upi' ? t('UPI') : t('Card'), rest: formatRupees(rest) }) : t('Enter the cash part')}
      </p>
      <div className="sheet-actions">
        <button className="primary" disabled={!ok} onClick={() => onApply({ cashPaise, other })}>
          {t("Split")}
        </button>
        <button onClick={onClose}>{t("Cancel")}</button>
      </div>
    </Sheet>
  );
}

/**
 * Whose bill it is. Typing a number looks the customer up when online (to reuse
 * their name and khata); offline, a new record is made and the server merges it
 * with any customer who has the same number.
 */
export function CustomerSheet({
  initial,
  credit,
  totalPaise,
  onClose,
  onApply,
}: {
  initial: BillCustomer | null;
  /** On credit: optionally part paid now in cash. */
  credit: { paidNowPaise: number } | null;
  totalPaise: number;
  onClose(): void;
  onApply(c: BillCustomer, paidNowPaise: number): void;
}) {
  useLang();
  const [phone, setPhone] = useState(initial?.phone ?? '');
  const [name, setName] = useState(initial?.name ?? '');
  const [known, setKnown] = useState<{ id: string; name: string; outstanding_paise: number } | null>(null);
  const [paidNow, setPaidNow] = useState(credit?.paidNowPaise ? String(credit.paidNowPaise / 100) : '');
  const phoneOk = /^\d{10}$/.test(phone);

  useEffect(() => {
    if (!phoneOk) return;
    let live = true;
    api
      .get<{ customers: { id: string; name: string; phone: string; outstanding_paise: number }[] }>(
        `/customers?q=${phone}`,
      )
      .then((r) => {
        const c = r.customers.find((x) => x.phone === phone) ?? null;
        if (!live) return;
        setKnown(c);
        if (c && !name) setName(c.name);
      })
      .catch(() => undefined); // offline: a new record, merged by number on the server
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phone, phoneOk]);

  const paidNowPaise = toPaise(paidNow);
  const ok = phoneOk && name.trim() !== '' && (!credit || paidNowPaise < totalPaise);
  return (
    <Sheet title={credit ? `On credit: ${formatRupees(totalPaise)}` : 'Customer'} onClose={onClose}>
      <label>
        {t("Phone")}
        <input
          inputMode="numeric"
          value={phone}
          maxLength={10}
          autoFocus
          onChange={(e) => {
            setPhone(e.target.value.replace(/\D/g, ''));
            setKnown(null);
          }}
        />
      </label>
      <label>
        {t("Name")}
        <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
      </label>
      {known && (
        <p className="muted" role="status">
          {known.outstanding_paise
            ? t('{name} already has a khata here: owes {amount}.', { name: known.name, amount: formatRupees(known.outstanding_paise) })
            : t('{name} already has a khata here.', { name: known.name })}
        </p>
      )}
      {credit && (
        <label>
          {t("Paid now in cash (₹, optional)")}
          <input inputMode="decimal" value={paidNow} onChange={(e) => rupeesOk(e.target.value) && setPaidNow(e.target.value)} />
        </label>
      )}
      {credit && ok && (
        <p className="num" role="status">
          {t("{amount} goes on {name}'s khata", { amount: formatRupees(totalPaise - paidNowPaise), name: name.trim() })}
        </p>
      )}
      <div className="sheet-actions">
        <button
          className="primary"
          disabled={!ok}
          onClick={() =>
            onApply(
              // A known customer keeps their id; a changed number is a new customer.
              { id: known?.id ?? (initial?.phone === phone ? initial.id : uuidv7()), phone, name: name.trim() },
              credit ? paidNowPaise : 0,
            )
          }
        >
          {credit ? t("Put on credit") : t("Save customer")}
        </button>
        <button onClick={onClose}>{t("Cancel")}</button>
      </div>
    </Sheet>
  );
}

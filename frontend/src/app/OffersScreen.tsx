/**
 * The outlet's offers (README, "9.19"): codes customers type in their cart on the food court app.
 * The outlet pays for its own offers; the server works out what each takes off.
 */
import { Hint } from './Hint';
import { useCallback, useEffect, useState } from 'react';
import { rupeesToPaise } from '../lib/foodcourt';
import { t } from '../lib/i18n';
import { toast } from '../lib/toast';
import { cleanCode, offerState, offerText, type Offer } from '../lib/offers';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading } from './Status';

const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

export function OffersScreen() {
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState('');
  const [kind, setKind] = useState<'percent' | 'amount'>('percent');
  const [value, setValue] = useState('10');
  const [min, setMin] = useState('');
  const [cap, setCap] = useState('');
  const [until, setUntil] = useState('');
  const [uses, setUses] = useState('');

  const load = useCallback(async () => {
    try {
      setOffers((await api.get<{ coupons: Offer[] }>('/coupons')).coupons);
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const cleaned = cleanCode(code);
  const valueNum = kind === 'percent' ? Number(value) : (rupeesToPaise(value) ?? 0);
  const valid =
    cleaned !== null &&
    (kind === 'percent' ? Number.isInteger(valueNum) && valueNum >= 1 && valueNum <= 100 : valueNum > 0 && valueNum % 100 === 0) &&
    (min === '' || rupeesToPaise(min) !== null) &&
    (cap === '' || kind === 'amount' || rupeesToPaise(cap) !== null) &&
    (uses === '' || (Number.isInteger(Number(uses)) && Number(uses) > 0));

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ coupons: Offer[] }>('/coupons', {
        code: cleaned,
        kind,
        value: valueNum,
        min_order_paise: min === '' ? 0 : rupeesToPaise(min),
        max_discount_paise: kind === 'percent' && cap !== '' ? rupeesToPaise(cap) : null,
        valid_until: until || null,
        max_uses: uses === '' ? null : Number(uses),
      });
      setOffers(r.coupons);
      toast(t('Offer saved'));
      setAdding(false);
      setCode('');
      setMin('');
      setCap('');
      setUntil('');
      setUses('');
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggle(o: Offer) {
    setBusy(true);
    try {
      setOffers((await api.patch<{ coupons: Offer[] }>(`/coupons/${o.id}`, { is_active: !o.is_active })).coupons);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const stateText = { on: t('Working'), off: t('Switched off'), expired: t('Expired'), used_up: t('Used up') };

  return (
    <section className="offers">
      <header className="manage-head">
        <h1>{t('Offers')}</h1>
        <button onClick={() => setAdding(!adding)}>{adding ? t('Cancel') : t('+ New offer')}</button>
      </header>
      <Hint>
        {t('Customers type the code in their cart on the food court app. You give up that money, and the food court fee is worked out on what they actually pay.')}
      </Hint>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {adding && (
        <form
          className="panel-inline"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <label>
            {t('Code')}
            <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={20} placeholder="DIWALI10" />
          </label>
          <div role="radiogroup" aria-label={t('What it takes off')} className="offer-kind">
            <button type="button" role="radio" aria-checked={kind === 'percent'} onClick={() => setKind('percent')}>
              {t('A percentage')}
            </button>
            <button type="button" role="radio" aria-checked={kind === 'amount'} onClick={() => setKind('amount')}>
              {t('Rupees off')}
            </button>
          </div>
          <label>
            {kind === 'percent' ? t('Percent off (1 to 100)') : t('Rupees off (whole rupees)')}
            <input value={value} inputMode="decimal" onChange={(e) => setValue(e.target.value)} />
          </label>
          <label>
            {t('Smallest order (₹, optional)')}
            <input value={min} inputMode="decimal" onChange={(e) => setMin(e.target.value)} />
          </label>
          {kind === 'percent' && (
            <label>
              {t('Most it can take off (₹, optional)')}
              <input value={cap} inputMode="decimal" onChange={(e) => setCap(e.target.value)} />
            </label>
          )}
          <label>
            {t('Last day (optional)')}
            <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
          </label>
          <label>
            {t('Most times it can be used in all (optional)')}
            <input value={uses} inputMode="numeric" onChange={(e) => setUses(e.target.value)} />
          </label>
          <p className="muted">{t('Each customer can use a code once. At least ₹1 is always left to pay.')}</p>
          <button className="primary" disabled={busy || !valid}>
            {t('Make the offer')}
          </button>
        </form>
      )}
      {offers === null ? (
        !error && <Loading />
      ) : offers.length === 0 ? (
        <p className="muted">{t('No offers yet.')}</p>
      ) : (
        <ul className="sop-list" aria-label={t('Offers')}>
          {offers.map((o) => {
            const st = offerState(o, today());
            return (
              <li key={o.id} className="offer-row">
                <span>
                  <strong>{o.code}</strong> · {offerText(o)}
                  <br />
                  <span className="muted">
                    {stateText[st]} · {o.uses === 1 ? t('used once') : t('used {n} times', { n: o.uses })}
                    {o.max_uses !== null ? ` / ${o.max_uses}` : ''}
                    {o.valid_until ? ` · ${t('until {date}', { date: o.valid_until })}` : ''}
                  </span>
                </span>
                <button disabled={busy} onClick={() => void toggle(o)}>
                  {o.is_active ? t('Switch off') : t('Switch on')}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

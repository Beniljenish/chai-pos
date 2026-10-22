/**
 * Small helpers for the owner (README, "9.17"): what delivery apps cost, what to have ready
 * tomorrow, dishes that hide themselves when their ingredient is gone, and the end-of-day message.
 */
import { useEffect, useState } from 'react';
import { commission, percentToBp } from '../lib/commission';
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import { formatQty, type BaseUnit } from '../lib/qty';
import { rupeesToPaise } from '../lib/foodcourt';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading } from './Status';

interface HelperShop {
  auto_sold_out: boolean;
  summary_phone: string | null;
  summary_on: boolean;
}
interface Tomorrow {
  weekday: string;
  items: { ingredient_id: string; name: string; base_unit: BaseUnit; qty: string }[];
}

const KEY = 'chai.commission';
function remembered(): { sales: string; app: string; direct: string } {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '{}');
    return { sales: v.sales ?? '', app: v.app ?? '25', direct: v.direct ?? '2' };
  } catch {
    return { sales: '', app: '25', direct: '2' };
  }
}

function Calculator() {
  const [v, setV] = useState(remembered);
  const sales = rupeesToPaise(v.sales);
  const app = percentToBp(v.app);
  const direct = percentToBp(v.direct);
  const result = sales !== null && app !== null && direct !== null ? commission(sales, app, direct) : null;
  function change(next: typeof v) {
    setV(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* private window: the numbers are just not remembered */
    }
  }
  return (
    <section className="panel-inline" aria-label={t('What delivery apps cost you')}>
      <h2>{t('What delivery apps cost you')}</h2>
      <label>
        {t('Sales through the apps this month (₹)')}
        <input value={v.sales} inputMode="decimal" onChange={(e) => change({ ...v, sales: e.target.value })} />
      </label>
      <label>
        {t('Their commission and charges (%)')}
        <input value={v.app} inputMode="decimal" onChange={(e) => change({ ...v, app: e.target.value })} />
      </label>
      <label>
        {t('What a direct order costs you (%, mostly the payment fee)')}
        <input value={v.direct} inputMode="decimal" onChange={(e) => change({ ...v, direct: e.target.value })} />
      </label>
      {result && (
        <p>
          {t('You paid')} <strong className="num">{formatRupees(result.paidPaise)}</strong> ·{' '}
          {t('the same orders direct would cost')} <strong className="num">{formatRupees(result.directPaise)}</strong>
          {result.savePaise > 0 && (
            <>
              {' '}
              · {t('you could keep')} <strong className="num">{formatRupees(result.savePaise)}</strong>
            </>
          )}
        </p>
      )}
      <p className="muted">{t('Type your own numbers: the app does not know what the apps charge you.')}</p>
    </section>
  );
}

function Prep() {
  const [data, setData] = useState<Tomorrow | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<Tomorrow>('/stock/tomorrow').then(setData, (e) => setError(explainError(e)));
  }, []);
  return (
    <section className="panel-inline" aria-label={t('Tomorrow’s prep')}>
      <h2>
        {t('Tomorrow’s prep')}
        {data ? ` (${data.weekday})` : ''}
      </h2>
      {error && <p className="error" role="alert">{error}</p>}
      {!data && !error && <Loading />}
      {data && data.items.length === 0 && <p className="muted">{t('Nothing to suggest yet: it needs a few weeks of sales.')}</p>}
      {data && data.items.length > 0 && (
        <ul className="sop-list">
          {data.items.map((i) => (
            <li key={i.ingredient_id}>
              <span>{i.name}</span>
              <strong className="num">≈ {formatQty(i.qty, i.base_unit)}</strong>
            </li>
          ))}
        </ul>
      )}
      <p className="muted">{t('Average of the last 4 same weekdays. A guide, not a promise.')}</p>
    </section>
  );
}

interface Wasted {
  total_paise: number;
  entries: number;
  items: { name: string; paise: number }[];
  worst_day: { weekday: string; paise: number; top_reason: string } | null;
}

function WastedCard() {
  const [w, setW] = useState<Wasted | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<Wasted>('/reports/wasted?days=28').then(setW, (e) => setError(explainError(e)));
  }, []);
  return (
    <section className="panel-inline" aria-label={t('What you wasted')}>
      <h2>{t('What you wasted')}</h2>
      {error && <p className="error" role="alert">{error}</p>}
      {!w && !error && <Loading />}
      {w && w.entries === 0 && <p className="muted">{t('Nothing wasted in the last 4 weeks, or nothing written down yet.')}</p>}
      {w && w.entries > 0 && (
        <>
          <p>
            {t('Last 4 weeks')}: <strong className="num">{formatRupees(w.total_paise)}</strong>
          </p>
          <ul className="sop-list">
            {w.items.map((i) => (
              <li key={i.name}>
                <span>{i.name}</span>
                <strong className="num">{formatRupees(i.paise)}</strong>
              </li>
            ))}
          </ul>
          {w.worst_day && (
            <p>
              <strong>{t('Most on {day}', { day: t(w.worst_day.weekday) })}</strong>
              <br />
              <span className="muted">
                {t('{amount} of it, mostly “{reason}”', { amount: formatRupees(w.worst_day.paise), reason: t(w.worst_day.top_reason) })}
              </span>
            </p>
          )}
        </>
      )}
      <p className="muted">{t('Only losses you wrote down and that count (not ones still waiting for you, or rejected).')}</p>
    </section>
  );
}

function Switches() {
  const [shop, setShop] = useState<HelperShop | null>(null);
  const [phone, setPhone] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get<HelperShop>('/shop').then((s) => {
      setShop(s);
      setPhone(s.summary_phone ?? '');
    }, (e) => setNote(explainError(e)));
  }, []);

  async function save(body: Partial<HelperShop>) {
    setBusy(true);
    setNote(null);
    try {
      const s = await api.patch<HelperShop>('/shop', body);
      setShop(s);
      setPhone(s.summary_phone ?? '');
    } catch (e) {
      setNote(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setNote(null);
    try {
      const r = await api.post<{ status: string; text: string; detail?: string }>('/shop/summary/test', {});
      setNote(
        r.status === 'sent'
          ? t('Sent. This is what you will get:') + '\n' + r.text
          : r.status === 'logged'
            ? t('No message service is set up on the server yet. This is what would be sent:') + '\n' + r.text
            : t('Could not send: ') + (r.detail ?? ''),
      );
    } catch (e) {
      setNote(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  if (!shop) return note ? <p className="error" role="alert">{note}</p> : <Loading />;
  return (
    <section className="panel-inline" aria-label={t('Switches')}>
      <div className="fc-switch">
        <div>
          <strong>{t('Hide a dish when its ingredient runs out')}</strong>
          <p className="muted">{t('Only for ingredients you have counted. Customers see “Sold out”; it clears when stock comes in.')}</p>
        </div>
        <button
          role="switch"
          aria-checked={shop.auto_sold_out}
          aria-label={t('Hide a dish when its ingredient runs out')}
          className={`fc-toggle ${shop.auto_sold_out ? 'on' : ''}`}
          disabled={busy}
          onClick={() => void save({ auto_sold_out: !shop.auto_sold_out })}
        >
          <span />
        </button>
      </div>
      <div className="fc-switch">
        <div>
          <strong>{t('Daily summary message')}</strong>
          <p className="muted">{t('Yesterday’s sales on your phone every morning.')}</p>
        </div>
        <button
          role="switch"
          aria-checked={shop.summary_on}
          aria-label={t('Daily summary message')}
          className={`fc-toggle ${shop.summary_on ? 'on' : ''}`}
          disabled={busy || !shop.summary_phone}
          onClick={() => void save({ summary_on: !shop.summary_on })}
        >
          <span />
        </button>
      </div>
      <label>
        {t('Your mobile number')}
        <input value={phone} inputMode="tel" onChange={(e) => setPhone(e.target.value)} />
      </label>
      <button disabled={busy || phone === (shop.summary_phone ?? '')} onClick={() => void save({ summary_phone: phone })}>
        {t('Save number')}
      </button>{' '}
      <button className="quiet" disabled={busy || !shop.summary_phone} onClick={() => void test()}>
        {t('Send me one now')}
      </button>
      {note && (
        <p role="status" style={{ whiteSpace: 'pre-line' }}>
          {note}
        </p>
      )}
    </section>
  );
}

export function HelpersScreen() {
  return (
    <section className="helpers">
      <header className="manage-head">
        <h1>{t('Helpers')}</h1>
      </header>
      <Calculator />
      <Prep />
      <WastedCard />
      <Switches />
    </section>
  );
}

/**
 * Owner: three things to keep an eye on (README, "9.16"): UPI bills the shop's account never saw,
 * everything that took money out of a sale today, and how close turnover is to the GST limit.
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { businessDate } from '../lib/billing';
import { formatRupees } from '../lib/gst';
import { t, useLang } from '../lib/i18n';
import {
  barPercent,
  daysBefore,
  limitToPaise,
  upiVerdict,
  type Changes,
  type GstWatch,
  type UpiMatch,
} from '../lib/watch';
import { api } from './apiClient';
import { explainError } from './errors';
import { Sheet } from './Sheet';
import { Loading, LoadError } from './Status';
import { clock, FactList, TrailPanel } from './TrailPanel';

type Tab = 'upi' | 'changes' | 'gst';
const TABS: [Tab, string][] = [
  ['upi', 'UPI match'],
  ['changes', 'Changes'],
  ['gst', 'GST limit'],
];

export function WatchScreen() {
  useLang();
  const [tab, setTab] = useState<Tab>('upi');
  return (
    <section className="watch">
      <header className="manage-head">
        <h1>{t('Watch')}</h1>
      </header>
      <p className="muted">{t('Things worth a look, worked out from your records. Nothing here is a guess.')}</p>
      <div className="chips" role="tablist" aria-label={t('Watch')}>
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" className="chip" aria-selected={tab === id} aria-pressed={tab === id} onClick={() => setTab(id)}>
            {t(label)}
          </button>
        ))}
      </div>
      {tab === 'upi' ? <UpiTab /> : tab === 'changes' ? <ChangesTab /> : <GstTab />}
    </section>
  );
}

// ---------------------------------------------------------------- UPI match
const RANGES: [number, string][] = [
  [0, 'Today'],
  [6, '7 days'],
  [29, '30 days'],
];

function UpiTab() {
  const [back, setBack] = useState(6);
  const [data, setData] = useState<UpiMatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ id: string; no: string } | null>(null);

  const load = useCallback(async () => {
    const to = businessDate(new Date());
    try {
      setData(await api.get<UpiMatch>(`/reports/upi-match?from=${daysBefore(to, back)}&to=${to}`));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [back]);
  useEffect(() => {
    void load();
  }, [load]);

  const verdict = data ? upiVerdict(data) : null;
  return (
    <>
      <p className="muted">
        {t('Every UPI bill against the money Razorpay confirmed. A bill rung as UPI that Razorpay never saw may have been paid to another QR.')}
      </p>
      <div className="chips" role="group" aria-label={t('Period')}>
        {RANGES.map(([days, label]) => (
          <button key={days} className="chip" aria-pressed={back === days} onClick={() => setBack(days)}>
            {t(label)}
          </button>
        ))}
      </div>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {data === null ? (
        !error && <Loading />
      ) : (
        <>
          {verdict === 'off' && (
            <p className="cx-note">
              {t('UPI through Razorpay is not set up for this shop, so there is nothing to compare yet. Turn it on in Shop & GST.')}
            </p>
          )}
          {verdict !== 'off' && (
            <div className={`watch-card ${verdict === 'clean' ? 'ok' : 'warn'}`}>
              <strong>{verdict === 'clean' ? t('Every UPI bill matches.') : t('Some UPI bills need a look.')}</strong>
              <span className="num">
                {t('{n} UPI bills · billed {billed} · confirmed {confirmed}', {
                  n: data.upi_bills,
                  billed: formatRupees(data.upi_billed_paise),
                  confirmed: formatRupees(data.confirmed_paise),
                })}
              </span>
            </div>
          )}
          {data.unconfirmed.length > 0 && (
            <>
              <h2>{t('No confirmed payment')}</h2>
              <ul className="watch-list">
                {data.unconfirmed.map((u) => (
                  <li key={u.bill_id}>
                    <div>
                      <strong className="num">{u.invoice_no}</strong> · {formatRupees(u.upi_paise)}
                      <small className="muted">
                        {u.cashier} · {clock(u.sold_at)} · {t(STATE[u.state])}
                      </small>
                    </div>
                    <button className="quiet" onClick={() => setOpen({ id: u.bill_id, no: u.invoice_no })}>
                      {t('History')}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {data.differs.length > 0 && (
            <>
              <h2>{t('Different amount')}</h2>
              <ul className="watch-list">
                {data.differs.map((d) => (
                  <li key={d.bill_id}>
                    <div>
                      <strong className="num">{d.invoice_no}</strong>
                      <small className="muted">
                        {t('Billed {billed}, Razorpay got {paid}', { billed: formatRupees(d.upi_paise), paid: formatRupees(d.paid_paise) })} · {d.cashier}
                      </small>
                    </div>
                    <button className="quiet" onClick={() => setOpen({ id: d.bill_id, no: d.invoice_no })}>
                      {t('History')}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {data.paid_for_void.length > 0 && (
            <>
              <h2>{t('Paid, then voided: refund due')}</h2>
              <ul className="watch-list">
                {data.paid_for_void.map((p) => (
                  <li key={p.bill_id}>
                    <div>
                      <strong className="num">{p.invoice_no}</strong> · {formatRupees(p.paid_paise)}
                    </div>
                    <button className="quiet" onClick={() => setOpen({ id: p.bill_id, no: p.invoice_no })}>
                      {t('History')}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {data.by_cashier.length > 0 && verdict !== 'off' && (
            <>
              <h2>{t('By cashier')}</h2>
              <table className="sales-table">
                <thead>
                  <tr>
                    <th scope="col">{t('Cashier')}</th>
                    <th scope="col" className="num">{t('UPI bills')}</th>
                    <th scope="col" className="num">{t('No payment seen')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_cashier.map((c) => (
                    <tr key={c.name}>
                      <th scope="row">{c.name}</th>
                      <td className="num">{c.upi_bills}</td>
                      <td className="num">
                        {c.unconfirmed} {c.unconfirmed > 0 && `(${formatRupees(c.unconfirmed_paise)})`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
      {open && (
        <Sheet title={<span className="num">{open.no}</span>} label={`Bill ${open.no}`} onClose={() => setOpen(null)}>
          <TrailPanel billId={open.id} />
        </Sheet>
      )}
    </>
  );
}

const STATE: Record<string, string> = {
  none: 'no Razorpay payment started',
  created: 'payment started, never finished',
  failed: 'payment failed',
};

// ---------------------------------------------------------------- the day's changes
function ChangesTab() {
  const today = businessDate(new Date());
  const [day, setDay] = useState(today);
  const [data, setData] = useState<Changes | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ id: string; no: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get<Changes>(`/reports/changes?date=${day}`));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [day]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <p className="muted">{t('Everything that took money or items out of a sale: voids, discounts, cancelled items and late bills.')}</p>
      <label className="watch-date">
        {t('Day')}
        <input type="date" value={day} max={today} onChange={(e) => e.target.value && setDay(e.target.value)} />
      </label>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {data === null ? (
        !error && <Loading />
      ) : data.rows.length === 0 ? (
        <p className="alerts-clear">{t('Nothing was taken out of a sale on this day.')}</p>
      ) : (
        <>
          <p className="muted">
            {Object.entries(data.counts)
              .map(([k, n]) => `${n} ${t(KIND[k] ?? k)}`)
              .join(' · ')}
          </p>
          <FactList facts={data.rows} />
          <ul className="watch-list">
            {data.rows
              .filter((r) => r.bill_id)
              .map((r, i) => (
                <li key={`${r.bill_id}-${i}`}>
                  <div>
                    <strong>{t(r.title)}</strong>
                    <small className="muted">{clock(r.at)}</small>
                  </div>
                  <button className="quiet" onClick={() => setOpen({ id: r.bill_id!, no: r.title })}>
                    {t('History')}
                  </button>
                </li>
              ))}
          </ul>
        </>
      )}
      {open && (
        <Sheet title={open.no} label={open.no} onClose={() => setOpen(null)}>
          <TrailPanel billId={open.id} />
        </Sheet>
      )}
    </>
  );
}

const KIND: Record<string, string> = {
  void: 'voids',
  discount: 'discounts',
  late: 'late bills',
  order_cancel: 'items cancelled',
  order_cancel_order: 'orders cancelled',
};

// ---------------------------------------------------------------- the GST limit
function GstTab() {
  const [data, setData] = useState<GstWatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState('');
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const g = await api.get<GstWatch>('/reports/gst-watch');
      setData(g);
      setLimit(g.threshold_paise ? String(g.threshold_paise / 100) : '');
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function save(e: FormEvent) {
    e.preventDefault();
    const paise = limit.trim() === '' ? null : limitToPaise(limit);
    if (limit.trim() !== '' && paise === null) return setSaveError(t('Type the limit in whole rupees, for example 2000000.'));
    setBusy(true);
    setSaveError(null);
    try {
      await api.patch('/shop', { gst_threshold_paise: paise });
      await load();
    } catch (err) {
      setSaveError(explainError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="muted">
        {t('A shop that is not registered for GST must register once a year’s turnover (before GST) passes a limit. This watches that for you.')}
      </p>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {data === null ? (
        !error && <Loading />
      ) : (
        <>
          <div className={`watch-card ${data.status === 'over' ? 'warn' : data.status === 'watch' ? 'look' : data.status === 'no_threshold' ? '' : 'ok'}`}>
            <strong>{t(GST_TITLE[data.status])}</strong>
            <span className="num">
              {t('This financial year (from {from}): {turnover} before GST', {
                from: data.fy_from,
                turnover: formatRupees(data.turnover_paise),
              })}
            </span>
          </div>
          {data.threshold_paise !== null && (
            <div className="gst-bar" role="img" aria-label={t('{n}% of the limit used', { n: data.percent ?? 0 })}>
              <i style={{ width: `${barPercent(data.percent)}%` }} className={data.status} />
              <span className="num">
                {t('{n}% of {limit}', { n: data.percent ?? 0, limit: formatRupees(data.threshold_paise) })}
              </span>
            </div>
          )}
          {data.cross_on && data.status !== 'registered' && (
            <p className="muted">{t('At the pace of the last 60 days you would pass it around {date}.', { date: data.cross_on })}</p>
          )}
          {data.status !== 'registered' && (
            <form className="cx-form watch-limit" onSubmit={save}>
              <label>
                {t('Your registration limit (₹ a year)')}
                <input value={limit} inputMode="numeric" onChange={(e) => setLimit(e.target.value)} placeholder="2000000" />
              </label>
              <p className="muted">
                {t('Ask your accountant which limit applies to you. It depends on whether you sell services or goods and on your state. Leave empty to switch the watch off.')}
              </p>
              {saveError && (
                <p className="error" role="alert">
                  {saveError}
                </p>
              )}
              <button className="primary" disabled={busy}>
                {busy ? t('Saving…') : t('Save limit')}
              </button>
            </form>
          )}
        </>
      )}
    </>
  );
}

const GST_TITLE: Record<string, string> = {
  registered: 'Your shop is registered for GST: no registration limit to watch.',
  no_threshold: 'Type your registration limit to start the watch.',
  safe: 'Well under your limit.',
  watch: 'Getting close to your limit.',
  over: 'Turnover is past your registration limit.',
};

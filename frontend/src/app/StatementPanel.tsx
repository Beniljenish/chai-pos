/**
 * One outlet's statement for a range of days, with a CSV for the accountant. The owner sees
 * their own; the super admin sees any outlet's. Both pass the loader (README, "9.17").
 */
import { useCallback, useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { presets, toCsv } from '../lib/reports';
import { feePercent, statementRows, type Statement } from '../lib/statement';
import { t } from '../lib/i18n';
import { Loading } from './Status';

const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

function save(name: string, rows: (string | number)[][]) {
  const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function StatementPanel({
  load,
  title,
}: {
  load(from: string, to: string): Promise<Statement>;
  title: string;
}) {
  const ranges = presets(today());
  const [range, setRange] = useState(ranges[0]);
  const [s, setS] = useState<Statement | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setS(null);
    setError(null);
    try {
      setS(await load(range.from, range.to));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the statement.');
    }
  }, [load, range]);

  useEffect(() => {
    void run();
  }, [run]);

  return (
    <section className="panel-inline fc-statement" aria-label={title}>
      <h2>{title}</h2>
      <div className="fc-ranges" role="group" aria-label={t('Dates')}>
        {ranges.map((r) => (
          <button key={r.label} className={r.label === range.label ? 'primary' : 'quiet'} onClick={() => setRange(r)}>
            {t(r.label)}
          </button>
        ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!s && !error && <Loading />}
      {s && (
        <>
          <p className="muted">
            {s.from} → {s.to} · {t('food court fee')} {feePercent(s.fee_bp)}
          </p>
          <dl>
            <div>
              <dt>{t('Online sales')}</dt>
              <dd className="num">{formatRupees(s.sales_paise)}</dd>
            </div>
            <div>
              <dt>{t('Food court fee')}</dt>
              <dd className="num">−{formatRupees(s.fee_paise)}</dd>
            </div>
            <div>
              <dt>{t('Earned')}</dt>
              <dd className="num">{formatRupees(s.earned_paise)}</dd>
            </div>
            <div>
              <dt>{t('Cancelled and refunded')}</dt>
              <dd className="num">{formatRupees(s.refunds_paise)}</dd>
            </div>
            <div>
              <dt>{t('Paid to you in these days')}</dt>
              <dd className="num">{formatRupees(s.paid_out_paise)}</dd>
            </div>
            <div className="fc-owed">
              <dt>{t('Still due now')}</dt>
              <dd className="num">{formatRupees(s.owed_now_paise)}</dd>
            </div>
          </dl>
          {s.orders.some((o) => o.refund_pending) && (
            <p className="muted">{t('Some cancelled orders are waiting for their refund.')}</p>
          )}
          <button onClick={() => save(`statement-${s.from}-to-${s.to}.csv`, statementRows(s))}>
            {t('Download (CSV)')}
          </button>
        </>
      )}
    </section>
  );
}

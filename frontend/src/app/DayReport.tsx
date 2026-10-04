/** Owner's variance report for one day, and approval. */
import { useCallback, useEffect, useState } from 'react';
import { adherenceWords, reasonLabel } from '../lib/dayend';
import { formatRupees } from '../lib/gst';
import { formatDelta, formatQty } from '../lib/qty';
import type { DayReport as Report } from '../lib/types';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { explainError } from './errors';

export function DayReport({
  day,
  refreshKey,
  onApproved,
}: {
  day: string;
  refreshKey: number;
  onApproved?: () => void;
}) {
  const [rep, setRep] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRep(await api.get<Report>(`/day-counts/${day}/report`));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [day]);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function approve() {
    setBusy(true);
    try {
      setRep(await api.post<Report>(`/day-counts/${day}/approve`, {}));
      setConfirming(false);
      onApproved?.();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !rep) return <LoadError error={error} onRetry={() => void load()} />;
  if (!rep) return <Loading />;
  if (rep.lines.length === 0)
    return (
      <section className="report">
        <h2>Variance</h2>
        <p className="empty">Nothing counted for this day yet.</p>
      </section>
    );

  const net = rep.surplus_paise - rep.missing_paise;
  const unpriced = rep.lines.filter((l) => Number(l.variance) !== 0 && Number(l.cost_per_unit_paise) === 0);
  return (
    <section className="report" aria-labelledby="report-title">
      <h2 id="report-title">Variance</h2>
      <div className="report-totals">
        <div>
          <span className="muted">Missing</span>
          <strong className={`num ${rep.missing_paise ? 'neg' : ''}`}>{formatRupees(rep.missing_paise)}</strong>
        </div>
        <div>
          <span className="muted">Wasted (recorded)</span>
          <strong className="num">{formatRupees(rep.wastage_paise)}</strong>
        </div>
        <div>
          <span className="muted">Outside tolerance</span>
          <strong className="num">{rep.flagged_count}</strong>
        </div>
      </div>
      {unpriced.length > 0 && (
        <p className="warn">
          No purchase price yet for {unpriced.map((l) => l.name).join(', ')}, so their gap is not in the ₹ total. Enter
          the price with the next stock-in.
        </p>
      )}
      {rep.surplus_paise > 0 && (
        <p className="muted">
          Extra on the shelf: {formatRupees(rep.surplus_paise)} (net {formatRupees(net)}). Extra stock usually means a
          missing stock-in entry or a wrong count.
        </p>
      )}
      {Object.keys(rep.wastage_by_reason).length > 0 && (
        <p className="muted">
          Wastage:{' '}
          {Object.entries(rep.wastage_by_reason)
            .map(([r, p]) => `${reasonLabel(r)} ${formatRupees(p)}`)
            .join(' · ')}
        </p>
      )}
      <ul className="variance-list">
        {rep.lines.map((l) => {
          const words = adherenceWords(l.adherence_pct);
          return (
            <li key={l.ingredient_id} className={l.flagged ? 'flagged' : ''}>
              <details>
                <summary>
                  <span className="v-name">
                    <strong>{l.name}</strong>
                    {l.flagged && <span className="flag bad">Check</span>}
                    {l.recounted && <span className="flag wait">Recounted</span>}
                    {!l.has_opening && <span className="flag wait">No opening count</span>}
                  </span>
                  <span className={`num v-qty ${Number(l.variance) < 0 ? 'neg' : ''}`}>
                    {Number(l.variance) === 0 ? 'Exact' : formatDelta(l.variance, l.base_unit)}
                  </span>
                  <span className={`num v-rs ${l.variance_paise < 0 ? 'neg' : ''}`}>
                    {Number(l.variance) !== 0 && Number(l.cost_per_unit_paise) === 0
                      ? 'no price yet'
                      : l.variance_paise === 0
                        ? ''
                        : formatRupees(l.variance_paise)}
                  </span>
                  {words && <span className="v-words muted">{words}</span>}
                </summary>
                <dl className="breakdown num">
                  <dt>Opening</dt>
                  <dd>{formatQty(l.opening, l.base_unit)}</dd>
                  {Number(l.stock_in) !== 0 && (
                    <>
                      <dt>+ Stock in</dt>
                      <dd>{formatQty(l.stock_in, l.base_unit)}</dd>
                    </>
                  )}
                  {Number(l.prep_in) !== 0 && (
                    <>
                      <dt>+ Batches made</dt>
                      <dd>{formatQty(l.prep_in, l.base_unit)}</dd>
                    </>
                  )}
                  {Number(l.prep_out) !== 0 && (
                    <>
                      <dt>− Used in batches</dt>
                      <dd>{formatQty(l.prep_out, l.base_unit)}</dd>
                    </>
                  )}
                  {Number(l.sold) !== 0 && (
                    <>
                      <dt>− Sold (by recipe)</dt>
                      <dd>{formatQty(l.sold, l.base_unit)}</dd>
                    </>
                  )}
                  {Number(l.wasted) !== 0 && (
                    <>
                      <dt>− Wasted</dt>
                      <dd>{formatQty(l.wasted, l.base_unit)}</dd>
                    </>
                  )}
                  {Number(l.other) !== 0 && (
                    <>
                      <dt>± Other</dt>
                      <dd>{formatDelta(l.other, l.base_unit)}</dd>
                    </>
                  )}
                  <dt className="strong">= Should be</dt>
                  <dd className="strong">{formatQty(l.expected, l.base_unit)}</dd>
                  <dt className="strong">Counted</dt>
                  <dd className="strong">{formatQty(l.counted, l.base_unit)}</dd>
                  <dt>Tolerance</dt>
                  <dd>±{l.tolerance_bp / 100}% of use</dd>
                </dl>
              </details>
            </li>
          );
        })}
      </ul>

      {rep.status === 'approved' ? (
        <p className="ok">
          Closed{rep.approved_by_name ? ` by ${rep.approved_by_name}` : ''}. Counted stock is now the stock on hand.
          {rep.late_bills > 0 &&
            ` ${rep.late_bills} bill${rep.late_bills === 1 ? '' : 's'} arrived after closing and explain ${formatRupees(rep.late_bills_explained_paise)} of the missing amount.`}
        </p>
      ) : rep.status === 'submitted' && rep.wastage_pending > 0 ? (
        <p className="warn">
          {rep.wastage_pending} wastage {rep.wastage_pending === 1 ? 'entry is' : 'entries are'} waiting for you (above).
          Accept or reject {rep.wastage_pending === 1 ? 'it' : 'them'} before closing the day.
        </p>
      ) : rep.status === 'submitted' ? (
        confirming ? (
          <div className="warn" role="alert">
            <p>
              Close this day? The counted stock becomes the stock on hand and the day is locked. The missing{' '}
              {formatRupees(rep.missing_paise)} stays on record.
            </p>
            <div className="sheet-actions">
              <button className="primary" disabled={busy} onClick={() => void approve()}>
                Yes, close the day
              </button>
              <button onClick={() => setConfirming(false)}>Not yet</button>
            </div>
          </div>
        ) : (
          <button className="primary" onClick={() => setConfirming(true)}>
            Approve and close the day
          </button>
        )
      ) : (
        <p className="muted">Waiting for recounts before the day can be closed.</p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

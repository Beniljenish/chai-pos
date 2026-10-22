/**
 * Owner: this shop's place in a food court. The owner sees the court and its QR and
 * switches their own outlet's "taking online orders" on and off. Making courts and
 * adding or removing outlets is the super admin's (/admin), not the owner's (README, "9.12").
 */
import { useCallback, useEffect, useState } from 'react';
import { courtPath } from '../lib/foodcourt';
import { formatRupees } from '../lib/gst';
import type { FoodCourtView } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { Qr } from './Qr';
import { StatementPanel } from './StatementPanel';
import type { Statement } from '../lib/statement';
import { Loading, LoadError } from './Status';

export function FoodCourtScreen() {
  const [v, setV] = useState<FoodCourtView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setV(await api.get<FoodCourtView>('/food-court'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function setPrep(minutes: number) {
    setBusy(true);
    setError(null);
    try {
      setV(await api.patch<FoodCourtView>('/food-court/me', { prep_minutes: Math.max(0, Math.min(180, minutes)) }));
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      setV(await api.patch<FoodCourtView>('/food-court/me', { accepting_orders: !v?.accepting_orders }));
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const court = v?.court ?? null;
  const link = court ? `${window.location.origin}${courtPath(court.slug)}` : '';

  return (
    <section className="foodcourt">
      <header className="manage-head">
        <h1>Food court</h1>
      </header>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {v === null ? (
        !error && <Loading />
      ) : court === null ? (
        <p className="muted">
          Your outlet is not in a food court. A food court&apos;s administrator adds outlets: ask them to add you, with
          this number as the owner&apos;s.
        </p>
      ) : (
        <>
          <p className="muted">{court.name}</p>

          <div className="panel-inline fc-switch">
            <div>
              <strong>Taking online orders</strong>
              <p className="muted">
                {v.accepting_orders
                  ? 'Customers can order from your outlet. New orders appear on your Tables screen.'
                  : 'Customers see your outlet as closed.'}
              </p>
            </div>
            <button
              role="switch"
              aria-checked={Boolean(v.accepting_orders)}
              aria-label="Taking online orders"
              className={`fc-toggle ${v.accepting_orders ? 'on' : ''}`}
              disabled={busy}
              onClick={() => void toggle()}
            >
              <span />
            </button>
          </div>

          <div className="panel-inline fc-switch">
            <div>
              <strong>Usual wait</strong>
              <p className="muted">
                {v.prep_minutes
                  ? `Customers are told "usually ready in about ${v.prep_minutes} min".`
                  : 'Customers are not told a wait. Set one so they know what to expect.'}
              </p>
            </div>
            <span className="fc-stepper" role="group" aria-label="Usual wait in minutes">
              <button disabled={busy || !v.prep_minutes} aria-label="5 minutes less" onClick={() => void setPrep((v.prep_minutes ?? 0) - 5)}>
                −
              </button>
              <strong className="num">{v.prep_minutes ? `${v.prep_minutes} min` : 'not set'}</strong>
              <button disabled={busy} aria-label="5 minutes more" onClick={() => void setPrep((v.prep_minutes ?? 0) + 5)}>
                +
              </button>
            </span>
          </div>

          {v.ratings && v.ratings.count > 0 && (
            <section className="panel-inline fc-ratings" aria-label="Ratings">
              <h2>
                {v.ratings.average} ★ <span className="muted">from {v.ratings.count} rating{v.ratings.count === 1 ? '' : 's'}</span>
              </h2>
              <ul>
                {v.ratings.recent
                  .filter((r) => r.comment)
                  .slice(0, 5)
                  .map((r) => (
                    <li key={r.at}>
                      <span aria-label={`${r.rating} stars`}>{'★'.repeat(r.rating)}</span> “{r.comment}” <span className="muted">· {r.name}</span>
                    </li>
                  ))}
              </ul>
            </section>
          )}

          {v.online_money && v.online_money.orders + v.online_money.settled_paise > 0 && (
            <section className="panel-inline fc-money" aria-label="Online payments">
              <h2>Online payments</h2>
              <p className="muted">Customers paid the food court for your orders. It pays you afterwards.</p>
              <dl>
                <div>
                  <dt>Paid by customers ({v.online_money.orders} order{v.online_money.orders === 1 ? '' : 's'})</dt>
                  <dd className="num">{formatRupees(v.online_money.paid_paise)}</dd>
                </div>
                <div>
                  <dt>Already paid to you</dt>
                  <dd className="num">{formatRupees(v.online_money.settled_paise)}</dd>
                </div>
                <div className="fc-owed">
                  <dt>Still due to you</dt>
                  <dd className="num">{formatRupees(v.online_money.owed_paise)}</dd>
                </div>
              </dl>
            </section>
          )}

          {v.online_money && v.online_money.orders > 0 && (
            <StatementPanel
              title="Statement"
              load={(from, to) => api.get<Statement>(`/food-court/statement?from=${from}&to=${to}`)}
            />
          )}

          <section className="fc-qr-card" aria-label="QR code to print">
            <Qr text={link} />
            <strong>{court.name}</strong>
            <span className="muted">Scan to order</span>
            <code>{link}</code>
          </section>
          <button className="quiet" onClick={() => window.print()}>
            Print the QR
          </button>

          <h2>Outlets in this food court</h2>
          <ul className="sop-list">
            {(v.outlets ?? []).map((o) => (
              <li key={o.id} className="fc-outlet">
                <span>
                  <strong>{o.name}</strong>
                  {o.is_me && <span className="muted"> · you</span>}
                  <br />
                  <span className="muted">{o.accepting_orders ? 'Taking orders' : 'Not taking orders'}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="muted">To join or leave a food court, ask its administrator.</p>
        </>
      )}
    </section>
  );
}

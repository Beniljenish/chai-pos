/**
 * Owner: this shop's place in a food court. The owner sees the court and its QR and
 * switches their own outlet's "taking online orders" on and off. Making courts and
 * adding or removing outlets is the super admin's (/admin), not the owner's (README, "9.12").
 */
import { useCallback, useEffect, useState } from 'react';
import { courtPath } from '../lib/foodcourt';
import type { FoodCourtView } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { Qr } from './Qr';
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

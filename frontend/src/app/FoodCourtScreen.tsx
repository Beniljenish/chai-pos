/**
 * Owner: this shop's place in a food court. A court has one QR for customers;
 * each outlet switches its own "taking orders" on and off, and joins only by
 * typing the host's code (README, "9.11").
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import qrcode from 'qrcode-generator';
import { courtPath } from '../lib/foodcourt';
import type { FoodCourtView } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading, LoadError } from './Status';
import { useSession } from './session';

/** The QR as SVG squares: drawn here, never sent to anyone to draw. */
function Qr({ text }: { text: string }) {
  const cells = useMemo(() => {
    const q = qrcode(0, 'M');
    q.addData(text);
    q.make();
    const n = q.getModuleCount();
    const dark: [number, number][] = [];
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) dark.push([r, c]);
    return { n, dark };
  }, [text]);
  const quiet = 3;
  const size = cells.n + quiet * 2;
  return (
    <svg
      className="fc-qr"
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="QR code for the food court's ordering page"
      shapeRendering="crispEdges"
    >
      <rect width={size} height={size} fill="#fff" />
      {cells.dark.map(([r, c]) => (
        <rect key={`${r}-${c}`} x={c + quiet} y={r + quiet} width="1" height="1" fill="#1b1530" />
      ))}
    </svg>
  );
}

export function FoodCourtScreen() {
  const { reloadCatalogue } = useSession();
  const [v, setV] = useState<FoodCourtView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
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

  async function act(run: () => Promise<FoodCourtView>) {
    setBusy(true);
    setError(null);
    try {
      setV(await run());
      // Being in a court is what puts the Tables screen (where customers' orders arrive)
      // on this till, so the till's copy of the menu and settings is refreshed.
      void reloadCatalogue();
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
        <>
          <p className="muted">
            A food court lets customers scan one QR code, pick any outlet, choose dishes and order. They pay at the
            outlet's counter.
          </p>
          <form
            className="panel-inline"
            onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post<FoodCourtView>('/food-court', { name: name.trim() }));
            }}
          >
            <h2>Start a food court</h2>
            <label>
              Name customers will see
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Marina Food Court" />
            </label>
            <button className="primary" disabled={busy || name.trim().length < 2}>
              Create food court
            </button>
          </form>
          <form
            className="panel-inline"
            onSubmit={(e) => {
              e.preventDefault();
              void act(() => api.post<FoodCourtView>('/food-court/join', { code: code.trim() }));
            }}
          >
            <h2>Join one</h2>
            <p className="muted">The host gives you a code. Nothing of yours is shared until you enter it.</p>
            <label>
              Code from the host
              <input value={code} onChange={(e) => setCode(e.target.value)} maxLength={12} autoCapitalize="characters" />
            </label>
            <button disabled={busy || code.trim().length < 4}>Join</button>
          </form>
        </>
      ) : (
        <>
          <p className="muted">
            {court.name} · you are {court.role === 'host' ? 'the host' : 'an outlet'}
          </p>

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
              onClick={() => void act(() => api.patch<FoodCourtView>('/food-court/me', { accepting_orders: !v.accepting_orders }))}
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

          <h2>Outlets</h2>
          <ul className="sop-list">
            {(v.outlets ?? []).map((o) => (
              <li key={o.id} className="fc-outlet">
                <span>
                  <strong>{o.name}</strong>
                  {o.is_host && <span className="muted"> · host</span>}
                  {o.is_me && <span className="muted"> · you</span>}
                  <br />
                  <span className="muted">{o.accepting_orders ? 'Taking orders' : 'Not taking orders'}</span>
                </span>
                {(court.role === 'host' || o.is_me) && !o.is_host && (
                  <button
                    className="quiet"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(o.is_me ? 'Leave this food court?' : `Remove ${o.name} from the food court?`)) {
                        void act(() => api.delete<FoodCourtView>(`/food-court/outlets/${o.id}`));
                      }
                    }}
                  >
                    {o.is_me ? 'Leave' : 'Remove'}
                  </button>
                )}
              </li>
            ))}
          </ul>

          {court.role === 'host' && court.join_code && (
            <div className="panel-inline">
              <h2>Invite an outlet</h2>
              <p className="muted">Give this code to the outlet's owner. They enter it under Manage → Food court.</p>
              <p className="fc-code" aria-label="Join code">
                {court.join_code}
              </p>
              <button className="quiet" disabled={busy} onClick={() => void act(() => api.post<FoodCourtView>('/food-court/code', {}))}>
                New code
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

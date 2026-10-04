/** Owner: a cashier's large wastage waits here for a yes or no (README, Phase 10.2). */
import { useCallback, useEffect, useState } from 'react';
import { reasonLabel } from '../lib/dayend';
import { formatRupees } from '../lib/gst';
import { formatQty } from '../lib/qty';
import type { WastageRow } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';

export function PendingWastage({ refreshKey, onDecided }: { refreshKey: number; onDecided: () => void }) {
  const [rows, setRows] = useState<WastageRow[]>([]);
  const [limit, setLimit] = useState<string | null>(null);
  const [savedLimit, setSavedLimit] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [pending, shop] = await Promise.all([
        api.get<WastageRow[]>('/wastage?pending=true'),
        api.get<{ wastage_approval_paise: number }>('/shop'),
      ]);
      setRows(pending);
      setLimit(String(shop.wastage_approval_paise / 100));
      setSavedLimit(String(shop.wastage_approval_paise / 100));
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function decide(id: string, accept: boolean) {
    setBusy(id);
    setError(null);
    try {
      await api.post(`/wastage/${id}/decision`, { accept });
      setRows((rs) => rs.filter((r) => r.id !== id));
      onDecided();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(null);
    }
  }

  async function saveLimit() {
    setError(null);
    try {
      const s = await api.patch<{ wastage_approval_paise: number }>('/shop', {
        wastage_approval_paise: Math.round(Number(limit) * 100),
      });
      setSavedLimit(String(s.wastage_approval_paise / 100));
    } catch (e) {
      setError(explainError(e));
    }
  }

  const validLimit = limit !== null && /^\d{1,6}$/.test(limit);
  return (
    <section className="pending-wastage" aria-labelledby="pending-wastage-title">
      <h2 id="pending-wastage-title">Wastage to check</h2>
      {rows.length === 0 ? (
        <p className="muted">Nothing waiting for you.</p>
      ) : (
        <ul className="ledger">
          {rows.map((r) => (
            <li key={r.id}>
              <span>
                {r.is_menu_item ? `${Number(r.qty)} × ${r.name}` : `${formatQty(r.qty, r.base_unit!)} ${r.name}`}
                <br />
                <span className="muted">
                  {reasonLabel(r.reason)} · {r.created_by_name} ·{' '}
                  {new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }).format(
                    new Date(r.created_at),
                  )}
                </span>
              </span>
              <span className="num right">{formatRupees(r.value_paise ?? 0)}</span>
              <span className="row-actions">
                <button disabled={busy === r.id} onClick={() => void decide(r.id, true)}>
                  Accept
                </button>
                <button disabled={busy === r.id} onClick={() => void decide(r.id, false)}>
                  Reject
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        Accept and it is a known loss. Reject and it is added back to stock, so it shows as missing at day end. The day
        cannot be closed while an entry is waiting.
      </p>
      {limit !== null && (
        <div className="inline-setting">
          <label>
            Ask me when a cashier's wastage is over (₹)
            <input inputMode="numeric" value={limit} onChange={(e) => setLimit(e.target.value)} />
          </label>
          <button disabled={!validLimit || limit === savedLimit} onClick={() => void saveLimit()}>
            Save
          </button>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

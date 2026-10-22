/** What was paid for each ingredient, and how the latest compares with the entries before it (README, "9.21"). */
import { useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import { api } from './apiClient';
import { explainError } from './errors';
import { Sheet } from './Sheet';
import { Loading } from './Status';

interface Row {
  ingredient_id: string;
  name: string;
  per: string;
  latest_paise: number;
  change_pct: number | null;
  on: string;
}
interface History {
  ingredient: string;
  per: string;
  entries: { date: string; supplier: string; paid_paise: number; price_paise: number }[];
}

export function PricesScreen() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<History | null>(null);
  useEffect(() => {
    api.get<{ items: Row[] }>('/stock/prices').then((r) => setRows(r.items), (e) => setError(explainError(e)));
  }, []);
  async function show(r: Row) {
    try {
      setOpen(await api.get<History>(`/stock/${r.ingredient_id}/prices`));
    } catch (e) {
      setError(explainError(e));
    }
  }
  return (
    <section className="prices">
      <header className="manage-head">
        <h1>{t('Prices paid')}</h1>
      </header>
      <p className="muted">{t('From your stock-in entries that had a price. The change is against the average of the entries before the latest.')}</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!rows && !error && <Loading />}
      {rows && rows.length === 0 && <p className="muted">{t('No prices yet. Add what you paid when you enter stock.')}</p>}
      {rows && rows.length > 0 && (
        <ul className="sop-list" aria-label={t('Prices paid')}>
          {rows.map((r) => (
            <li key={r.ingredient_id}>
              <button onClick={() => void show(r)}>
                <span className="sop-name">
                  <strong>{r.name}</strong>
                  <span className="muted"> · {t('per {unit}', { unit: t(r.per) })}</span>
                </span>
                <span className="sop-lines num">{formatRupees(r.latest_paise)}</span>
                {r.change_pct !== null && (
                  <span className={`flag ${r.change_pct >= 5 ? 'bad' : r.change_pct <= -5 ? 'ok' : ''}`}>
                    {r.change_pct > 0 ? '+' : ''}
                    {r.change_pct}%
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && (
        <Sheet title={`${open.ingredient} · ${t('per {unit}', { unit: t(open.per) })}`} onClose={() => setOpen(null)}>
          <ul className="sop-list">
            {open.entries.map((e, i) => (
              <li key={i}>
                <span>
                  {e.date}
                  {e.supplier && <span className="muted"> · {e.supplier}</span>}
                </span>
                <strong className="num">{formatRupees(e.price_paise)}</strong>
              </li>
            ))}
          </ul>
        </Sheet>
      )}
    </section>
  );
}

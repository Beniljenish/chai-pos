/**
 * Owner: what each item costs to make and keeps. Cost = the current recipe at
 * the latest price paid for each ingredient; revenue is the price without GST.
 */
import { t } from '../lib/i18n';
import { Hint } from './Hint';
import { useCallback, useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { marginTone, sortMargins, whyNoMargin, type MarginSort } from '../lib/margin';
import type { MarginItem } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading, LoadError } from './Status';

const SORTS: [MarginSort, string][] = [
  ['worst', 'Worst first'],
  ['best', 'Best first'],
  ['sales', 'By sales'],
];

export function MarginScreen() {
  const [items, setItems] = useState<MarginItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<MarginSort>('worst');

  const load = useCallback(async () => {
    try {
      setItems((await api.get<{ items: MarginItem[] }>('/reports/margin')).items);
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="margin">
      <header className="manage-head">
        <h1>Margin</h1>
        <button className="quiet" onClick={() => void load()}>
          Refresh
        </button>
      </header>
      <Hint>
        What each item costs to make and what is left. Cost is the recipe at the latest price you paid for each
        ingredient; the price is counted without GST.
      </Hint>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {items === null ? (
        !error && <Loading />
      ) : (
        <>
          <div className="chips" role="group" aria-label="Order the list">
            {SORTS.map(([id, label]) => (
              <button key={id} className="chip" aria-pressed={sort === id} onClick={() => setSort(id)}>
                {label}
              </button>
            ))}
          </div>
          <ul className="margin-list">
            {sortMargins(items, sort).map((i) => {
              const tone = marginTone(i.margin_pct);
              const costPct = i.cost_paise !== null && i.net_paise > 0 ? Math.round((i.cost_paise / i.net_paise) * 100) : 0;
              return (
                <li key={i.menu_item_id}>
                  <div className="margin-head">
                    <strong>{i.name}</strong>
                    {i.margin_pct !== null && <span className={`margin-pct margin-${tone}`}>{i.margin_pct}%</span>}
                  </div>
                  {i.margin_pct !== null && i.cost_paise !== null && i.margin_paise !== null ? (
                    <>
                      <p className="muted">
                        Sells {formatRupees(i.price_paise)} · costs {formatRupees(i.cost_paise)} · keeps{' '}
                        {formatRupees(i.margin_paise)}
                        {i.net_paise !== i.price_paise && ' (after GST)'}
                      </p>
                      <span className="margin-bar" aria-hidden="true">
                        <span className="margin-cost" style={{ width: `${Math.min(100, costPct)}%` }} />
                        <span className={`margin-kept margin-${tone}`} style={{ width: `${Math.max(0, 100 - costPct)}%` }} />
                      </span>
                    </>
                  ) : (
                    <p className="warn-line">{whyNoMargin(i)}</p>
                  )}
                </li>
              );
            })}
          </ul>
          {items.length === 0 && <p className="muted">{t("No items on the menu yet.")}</p>}
          <p className="muted">Pink is under 50% kept, amber up to 67%, green above.</p>
        </>
      )}
    </section>
  );
}

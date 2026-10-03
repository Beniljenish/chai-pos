/**
 * Owner's stock: what is on the shelf, stock-in, the one-time opening count,
 * and every movement behind each number. Online only: these are the owner's
 * records, not the counter's, and must not be edited from a stale copy.
 */
import { useCallback, useEffect, useState } from 'react';
import { formatQty } from '../lib/qty';
import type { Ingredient, StockRow } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { ItemSheet } from './ItemSheet';
import { PrepPanel } from './PrepPanel';

export function StockScreen() {
  const [rows, setRows] = useState<StockRow[] | null>(null);
  const [ingredients, setIngredients] = useState<Record<string, Ingredient>>({});
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [stock, all] = await Promise.all([
        api.get<StockRow[]>('/stock'),
        api.get<Ingredient[]>('/ingredients'),
      ]);
      setRows(stock.filter((r) => r.is_active));
      setIngredients(Object.fromEntries(all.map((i) => [i.id, i])));
      setError(null);
    } catch (e) {
      setError(explainError(e));
      setRows((r) => r ?? []);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const notCounted = rows?.filter((r) => !r.has_opening).length ?? 0;
  const openRow = rows?.find((r) => r.ingredient_id === open);

  return (
    <main className="manage">
      <header className="manage-head">
        <h1>Stock</h1>
        <button className="quiet" onClick={() => void load()}>
          Refresh
        </button>
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notCounted > 0 && (
        <p className="warn">
          {notCounted} item{notCounted === 1 ? ' has' : 's have'} no opening count yet. Count what is on the shelf
          and enter it once per item: the numbers below are only right after that.
        </p>
      )}

      {rows === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <ul className="stock-list">
          {rows.map((r) => (
            <li key={r.ingredient_id}>
              <button onClick={() => setOpen(r.ingredient_id)}>
                <span className="stock-name">
                  <strong>{r.name}</strong>
                  {r.kind === 'prep' && <span className="muted"> made here</span>}
                </span>
                <span className={`num stock-qty ${r.is_negative ? 'neg' : ''}`}>
                  {formatQty(r.on_hand, r.base_unit)}
                </span>
                <span className="stock-flags">
                  {!r.has_opening && <span className="flag wait">Not counted</span>}
                  {r.is_negative && <span className="flag bad">Below zero</span>}
                  {r.below_reorder && !r.is_negative && <span className="flag wait">Reorder</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <PrepPanel onLogged={() => void load()} />

      {openRow && ingredients[openRow.ingredient_id] && (
        <ItemSheet
          row={openRow}
          ingredient={ingredients[openRow.ingredient_id]}
          onClose={() => setOpen(null)}
          onChanged={() => void load()}
        />
      )}
    </main>
  );
}

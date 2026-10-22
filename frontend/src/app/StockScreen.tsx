/**
 * Owner's stock: what is on the shelf, stock-in, the one-time opening count,
 * and every movement behind each number. Online only: these are the owner's
 * records, not the counter's, and must not be edited from a stale copy.
 */
import { useCallback, useEffect, useState } from 'react';
import { formatQty } from '../lib/qty';
import { stockLevel, worstFirst, type Tone } from '../lib/stockLevel';
import type { Ingredient, StockRow } from '../lib/types';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { explainError } from './errors';
import { ItemSheet } from './ItemSheet';
import { PrepPanel } from './PrepPanel';
import { t } from '../lib/i18n';

export function StockScreen() {
  const [rows, setRows] = useState<StockRow[] | null>(null);
  const [ingredients, setIngredients] = useState<Record<string, Ingredient>>({});
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [sort, setSort] = useState<'worst' | 'az' | 'low'>('worst');

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
  const leveled = (rows ?? []).map((r) => ({
    ...r,
    level: stockLevel(r.on_hand, ingredients[r.ingredient_id]?.reorder_level),
  }));
  const isLow = (r: { level: { tone: Tone }; is_negative: boolean }) =>
    r.level.tone === 'bad' || r.level.tone === 'near' || r.is_negative;
  const listed =
    sort === 'worst'
      ? worstFirst(leveled)
      : sort === 'low'
        ? worstFirst(leveled.filter(isLow))
        : [...leveled].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <section className="stock">
      <header className="manage-head">
        <h1>{t("Stock")}</h1>
        <button className="quiet" onClick={() => void load()}>
          {t("Refresh")}
        </button>
      </header>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {notCounted > 0 && (
        <p className="warn">
          {notCounted} {t("item")}{notCounted === 1 ? ' has' : 's have'} {t("no opening count yet. Count what is on the shelf and enter it once per item: the numbers below are only right after that.")}
        </p>
      )}

      {rows === null ? (
        !error && <Loading />
      ) : (
        <>
        <div className="chips" role="group" aria-label={t("Order the list")}>
          {([['worst', 'Worst first'], ['az', 'A–Z'], ['low', 'Low only']] as const).map(([id, label]) => (
            <button key={id} className="chip" aria-pressed={sort === id} onClick={() => setSort(id)}>
              {label}
            </button>
          ))}
        </div>
        {listed.length === 0 && <p className="muted">{t("Nothing is low.")}</p>}
        <ul className="stock-list">
          {listed.map((r) => (
            <li key={r.ingredient_id}>
              <button onClick={() => setOpen(r.ingredient_id)}>
                <span className="stock-name">
                  <strong>{r.name}</strong>
                  {r.kind === 'prep' && <span className="muted"> {t("made here")}</span>}
                </span>
                <span className={`num stock-qty ${r.is_negative ? 'neg' : ''}`}>
                  {formatQty(r.on_hand, r.base_unit)}
                </span>
                <span className="stock-flags">
                  {!r.has_opening && <span className="flag wait">{t("Not counted")}</span>}
                  {r.is_negative && <span className="flag bad">{t("Below zero")}</span>}
                  {r.below_reorder && !r.is_negative && <span className="flag wait">{t("Reorder")}</span>}
                </span>
                {r.level.tickPct !== null && (
                  <span className={`level level-${r.level.tone}`} aria-hidden="true">
                    <span className="level-fill" style={{ width: `${r.level.fillPct}%` }} />
                    <span className="level-tick" style={{ left: `${r.level.tickPct}%` }} />
                  </span>
                )}
                {r.level.tickPct !== null && ingredients[r.ingredient_id]?.reorder_level && (
                  <span className="level-note muted">
                    reorder at {formatQty(ingredients[r.ingredient_id].reorder_level as string, r.base_unit)}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
        </>
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
    </section>
  );
}

/**
 * Logging a decoction batch moves stock: milk, tea powder and sugar out, decoction
 * in. If batches are not logged, raw stock never goes down and decoction goes
 * negative, so day-end variance would be wrong for both. Cashiers make the
 * batches, so they log them.
 */
import { useEffect, useState } from 'react';
import { formatQty, type BaseUnit } from '../lib/qty';
import type { Ingredient, PrepRecipe } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';

interface PrepItem {
  ingredient: Ingredient;
  recipe: PrepRecipe | null;
}

export function PrepPanel({ onLogged }: { onLogged?: () => void }) {
  const [items, setItems] = useState<PrepItem[] | null>(null);
  const [batches, setBatches] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const all = await api.get<Ingredient[]>('/ingredients');
        const preps = all.filter((i) => i.kind === 'prep' && i.is_active);
        const withRecipes = await Promise.all(
          preps.map(async (ingredient) => ({
            ingredient,
            recipe: await api.get<PrepRecipe | null>(`/ingredients/${ingredient.id}/recipe`),
          })),
        );
        setItems(withRecipes);
      } catch (e) {
        setMessage({ ok: false, text: explainError(e) });
        setItems([]);
      }
    })();
  }, []);

  async function log(item: PrepItem) {
    const n = batches[item.ingredient.id] ?? 1;
    setBusy(item.ingredient.id);
    setMessage(null);
    try {
      await api.post('/prep-batches', { ingredient_id: item.ingredient.id, batches: String(n) });
      const made = formatQty(Number(item.recipe?.yield_qty ?? 0) * n, item.ingredient.base_unit);
      setMessage({ ok: true, text: `Logged: ${n} batch${n === 1 ? '' : 'es'} of ${item.ingredient.name} (${made}).` });
      setBatches({ ...batches, [item.ingredient.id]: 1 });
      onLogged?.();
    } catch (e) {
      setMessage({ ok: false, text: explainError(e) });
    } finally {
      setBusy(null);
    }
  }

  if (items === null) return <p className="muted">Loading…</p>;
  if (items.length === 0 && !message) return null;

  return (
    <section className="prep" aria-labelledby="prep-title">
      <h2 id="prep-title">Made a batch?</h2>
      {items.map((item) => {
        const n = batches[item.ingredient.id] ?? 1;
        const unit = item.ingredient.base_unit;
        return (
          <div className="prep-card" key={item.ingredient.id}>
            <div>
              <strong>{item.ingredient.name}</strong>
              {item.recipe?.yield_qty ? (
                <p className="muted">
                  One batch makes {formatQty(item.recipe.yield_qty, unit)}:{' '}
                  {item.recipe.lines.map((l) => `${l.ingredient_name} ${formatQty(l.qty, l.base_unit as BaseUnit)}`).join(', ')}
                </p>
              ) : (
                <p className="warn">No batch recipe yet. The owner needs to add one.</p>
              )}
            </div>
            {item.recipe?.yield_qty && (
              <div className="prep-actions">
                <div className="stepper">
                  <button
                    aria-label="Half a batch less"
                    onClick={() => setBatches({ ...batches, [item.ingredient.id]: Math.max(0.5, n - 0.5) })}
                  >
                    −
                  </button>
                  <span className="num">{n}</span>
                  <button
                    aria-label="Half a batch more"
                    onClick={() => setBatches({ ...batches, [item.ingredient.id]: Math.min(20, n + 0.5) })}
                  >
                    +
                  </button>
                </div>
                <button className="primary" disabled={busy !== null} onClick={() => log(item)}>
                  Log {n} batch{n === 1 ? '' : 'es'}
                </button>
              </div>
            )}
          </div>
        );
      })}
      {message && (
        <p className={message.ok ? 'ok' : 'error'} role={message.ok ? 'status' : 'alert'}>
          {message.text}
        </p>
      )}
    </section>
  );
}

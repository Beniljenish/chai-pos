/** The ingredient list: add items and pack sizes, and mark packaging. */
import { useState } from 'react';
import { formatQty, type BaseUnit } from '../lib/qty';
import type { Ingredient } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';

const UNIT_LABEL: Record<BaseUnit, string> = { ml: 'ml (liquids)', g: 'g (solids)', piece: 'pieces (cups, lids…)' };

export function IngredientsPanel({ ingredients, onChanged }: { ingredients: Ingredient[]; onChanged(): void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [unit, setUnit] = useState<BaseUnit>('g');
  const [kind, setKind] = useState<'raw' | 'prep'>('raw');
  const [packFor, setPackFor] = useState<string | null>(null);
  const [packName, setPackName] = useState('');
  const [packSize, setPackSize] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
      return true;
    } catch (e) {
      setError(explainError(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function addIngredient() {
    const ok = await run(() =>
      api.post('/ingredients', {
        name: name.trim(),
        base_unit: unit,
        kind,
        // Pieces are almost always packaging: one per serving whatever the size.
        scales_with_size: unit !== 'piece',
      }),
    );
    if (ok) {
      setAdding(false);
      setName('');
    }
  }

  async function addPack(ingredientId: string) {
    const ok = await run(() =>
      api.post(`/ingredients/${ingredientId}/pack-units`, { name: packName.trim(), qty_in_base: String(Number(packSize)) }),
    );
    if (ok) {
      setPackFor(null);
      setPackName('');
      setPackSize('');
    }
  }

  return (
    <section aria-labelledby="ing-title">
      <h2 id="ing-title">Ingredients</h2>
      <ul className="ing-list">
        {ingredients
          .filter((i) => i.is_active)
          .map((i) => (
            <li key={i.id}>
              <div className="ing-head">
                <strong>{i.name}</strong>
                <span className="muted">
                  {i.kind === 'prep' ? 'made here' : 'bought'} · {i.base_unit === 'piece' ? 'pieces' : i.base_unit}
                </span>
              </div>
              <p className="muted ing-packs">
                {i.pack_units.length
                  ? `Comes in: ${i.pack_units.map((u) => `${u.name} (${formatQty(u.qty_in_base, i.base_unit)})`).join(', ')}`
                  : 'No pack sizes yet'}
              </p>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!i.scales_with_size}
                  disabled={busy}
                  onChange={(e) =>
                    void run(() => api.patch(`/ingredients/${i.id}`, { scales_with_size: !e.target.checked }))
                  }
                />
                Same amount for every size (cups, lids, straws)
              </label>
              {i.kind === 'raw' &&
                (packFor === i.id ? (
                  <div className="pack-form">
                    <label>
                      Pack name
                      <input value={packName} maxLength={30} placeholder="crate" onChange={(e) => setPackName(e.target.value)} />
                    </label>
                    <label>
                      Holds ({i.base_unit === 'piece' ? 'pieces' : i.base_unit})
                      <input
                        inputMode="decimal"
                        value={packSize}
                        placeholder="12000"
                        onChange={(e) => setPackSize(e.target.value.replace(/[^0-9.]/g, ''))}
                      />
                    </label>
                    <div className="sheet-actions">
                      <button
                        className="primary"
                        disabled={busy || !packName.trim() || !(Number(packSize) > 0)}
                        onClick={() => void addPack(i.id)}
                      >
                        Add pack size
                      </button>
                      <button onClick={() => setPackFor(null)}>Cancel</button>
                    </div>
                    <p className="muted">Pack sizes cannot be edited later (past deliveries were counted with them).</p>
                  </div>
                ) : (
                  <button className="quiet" onClick={() => setPackFor(i.id)}>
                    + Pack size
                  </button>
                ))}
            </li>
          ))}
      </ul>

      {adding ? (
        <div className="panel-inline">
          <label>
            Name
            <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="Ginger" />
          </label>
          <label>
            Measured in
            <select value={unit} onChange={(e) => setUnit(e.target.value as BaseUnit)}>
              {(Object.keys(UNIT_LABEL) as BaseUnit[]).map((u) => (
                <option key={u} value={u}>
                  {UNIT_LABEL[u]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Where it comes from
            <select value={kind} onChange={(e) => setKind(e.target.value as 'raw' | 'prep')}>
              <option value="raw">Bought</option>
              <option value="prep">Made here in batches (like decoction)</option>
            </select>
          </label>
          <p className="muted">The unit cannot be changed later: every stock number is kept in it.</p>
          <div className="sheet-actions">
            <button className="primary" disabled={busy || !name.trim()} onClick={() => void addIngredient()}>
              Add ingredient
            </button>
            <button onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setAdding(true)}>+ New ingredient</button>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

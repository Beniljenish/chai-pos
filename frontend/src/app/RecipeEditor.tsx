/**
 * Edit one SOP. Saving never changes the past: it creates a new version, and
 * bills already sold keep deducting by the version they were sold under.
 */
import { useEffect, useState } from 'react';
import { formatQty, type BaseUnit } from '../lib/qty';
import { fruitGramsPerPortion, toEditable, toPayload, validate, type EditLine, type JuiceInputs } from '../lib/recipe';
import type { Ingredient, Recipe } from '../lib/types';
import { api } from './apiClient';
import { Sheet } from './Sheet';
import { explainError } from './errors';

export type RecipeTarget =
  | { kind: 'menu'; id: string; name: string }
  | { kind: 'prep'; id: string; name: string; unit: BaseUnit };

interface Props {
  target: RecipeTarget;
  ingredients: Ingredient[];
  onClose(): void;
  onSaved(): void;
}

const when = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso));

let keySeq = 0;
const newKey = () => `new-${++keySeq}`;

export function RecipeEditor({ target, ingredients, onClose, onSaved }: Props) {
  const base = target.kind === 'menu' ? `/menu-items/${target.id}` : `/ingredients/${target.id}`;
  const [versions, setVersions] = useState<Recipe[] | null>(null);
  const [lines, setLines] = useState<EditLine[]>([]);
  const [juice, setJuice] = useState<JuiceInputs | null>(null);
  const [yieldQty, setYieldQty] = useState<string | null>(target.kind === 'prep' ? '' : null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  // A prep is made only from bought (raw) ingredients; drinks may use either.
  const choices = ingredients.filter((i) => i.is_active && (target.kind === 'menu' || i.kind === 'raw') && i.id !== target.id);
  const byId = Object.fromEntries(ingredients.map((i) => [i.id, i]));
  const fruits = ingredients.filter((i) => i.is_active && i.kind === 'raw' && i.base_unit === 'g');

  async function load() {
    try {
      const v = await api.get<Recipe[]>(`${base}/recipe/versions`);
      setVersions(v);
      const current = v[0] ?? null;
      const e = toEditable(current);
      setLines(e.lines);
      setJuice(e.juice);
      if (target.kind === 'prep') setYieldQty(current?.yield_qty ? String(Number(current.yield_qty)) : '');
      setDirty(false);
    } catch (err) {
      setError(explainError(err));
      setVersions([]);
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const edit = (fn: () => void) => {
    fn();
    setDirty(true);
    setError(null);
  };
  const setLine = (key: string, patch: Partial<EditLine>) =>
    edit(() => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l))));

  const problem = validate(lines, juice, yieldQty);
  const grams = juice ? fruitGramsPerPortion(Number(juice.ml_per_kg), Number(juice.portion_ml)) : null;

  async function save() {
    if (problem) return setError(problem);
    setBusy(true);
    try {
      await api.put(`${base}/recipe`, toPayload(lines, juice, yieldQty));
      await load();
      onSaved();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  const current = versions?.[0];

  return (
    <Sheet
      title={target.name}
      sub={
        <p className="muted">
          {current
            ? `Version ${current.version}, since ${when(current.effective_from)}`
            : 'No recipe yet: sales of this item do not take anything out of stock.'}
        </p>
      }
      onClose={onClose}
    >

      {versions === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <p className="muted">
            {target.kind === 'menu' ? 'What one serving uses.' : 'What one batch uses.'} Quantities are in each
            ingredient&apos;s unit.
          </p>
          <ul className="recipe-lines">
            {lines.map((l, i) => {
              const ing = byId[l.ingredient_id];
              return (
                <li key={l.key}>
                  <label className="sr-only" htmlFor={`ing-${l.key}`}>
                    Ingredient {i + 1}
                  </label>
                  <select
                    id={`ing-${l.key}`}
                    value={l.ingredient_id}
                    onChange={(e) => setLine(l.key, { ingredient_id: e.target.value })}
                  >
                    <option value="">Choose…</option>
                    {choices.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label={`Quantity of ${ing?.name ?? `ingredient ${i + 1}`}`}
                    inputMode="decimal"
                    value={l.qty}
                    onChange={(e) => setLine(l.key, { qty: e.target.value.replace(/[^0-9.]/g, '') })}
                  />
                  <span className="unit">{ing ? (ing.base_unit === 'piece' ? 'pcs' : ing.base_unit) : ''}</span>
                  <button
                    className="quiet"
                    aria-label={`Remove ${ing?.name ?? 'row'}`}
                    onClick={() => edit(() => setLines((ls) => ls.filter((x) => x.key !== l.key)))}
                  >
                    ✕
                  </button>
                </li>
              );
            })}
          </ul>
          <button
            onClick={() => edit(() => setLines((ls) => [...ls, { key: newKey(), ingredient_id: '', qty: '' }]))}
          >
            + Add ingredient
          </button>

          {target.kind === 'menu' &&
            (juice ? (
              <fieldset className="juice">
                <legend>Fresh juice: fruit worked out from the yield</legend>
                <label>
                  Fruit
                  <select
                    value={juice.ingredient_id}
                    onChange={(e) => edit(() => setJuice({ ...juice, ingredient_id: e.target.value }))}
                  >
                    {fruits.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="juice-row">
                  <label>
                    Juice from 1 kg (ml)
                    <input
                      inputMode="decimal"
                      value={juice.ml_per_kg}
                      onChange={(e) =>
                        edit(() => setJuice({ ...juice, ml_per_kg: e.target.value.replace(/[^0-9.]/g, '') }))
                      }
                    />
                  </label>
                  <label>
                    Glass (ml)
                    <input
                      inputMode="decimal"
                      value={juice.portion_ml}
                      onChange={(e) =>
                        edit(() => setJuice({ ...juice, portion_ml: e.target.value.replace(/[^0-9.]/g, '') }))
                      }
                    />
                  </label>
                </div>
                <p>
                  = <strong className="num">{grams === null ? '–' : formatQty(grams, 'g')}</strong> of{' '}
                  {byId[juice.ingredient_id]?.name ?? 'fruit'} per glass
                </p>
                <button className="quiet" onClick={() => edit(() => setJuice(null))}>
                  Stop using juice yield
                </button>
              </fieldset>
            ) : (
              fruits.length > 0 && (
                <button
                  className="quiet"
                  onClick={() =>
                    edit(() => setJuice({ ingredient_id: fruits[0].id, ml_per_kg: '', portion_ml: '' }))
                  }
                >
                  Fresh juice? Work out the fruit from the yield
                </button>
              )
            ))}

          {target.kind === 'prep' && (
            <label className="yield">
              One batch makes ({target.unit === 'piece' ? 'pieces' : target.unit})
              <input
                inputMode="decimal"
                value={yieldQty ?? ''}
                onChange={(e) => edit(() => setYieldQty(e.target.value.replace(/[^0-9.]/g, '')))}
              />
            </label>
          )}

          {dirty && (
            <div className="sheet-actions">
              <button className="primary" disabled={busy} onClick={save}>
                Save as version {(current?.version ?? 0) + 1}
              </button>
              <button onClick={() => void load()}>Undo changes</button>
            </div>
          )}
          {dirty && (
            <p className="muted">Bills already sold keep the recipe they were sold with. Only new sales use this.</p>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          {versions.length > 0 && (
            <details className="history">
              <summary>History ({versions.length} version{versions.length === 1 ? '' : 's'})</summary>
              <ol>
                {versions.map((v) => (
                  <li key={v.id}>
                    <strong>Version {v.version}</strong>{' '}
                    <span className="muted">
                      {when(v.effective_from)}
                      {v.created_by_name ? ` by ${v.created_by_name}` : ''}
                    </span>
                    <br />
                    {v.lines.map((l) => `${l.ingredient_name} ${formatQty(l.qty, l.base_unit as BaseUnit)}`).join(', ')}
                    {v.yield_qty && ` → makes ${formatQty(v.yield_qty, target.kind === 'prep' ? target.unit : 'ml')}`}
                  </li>
                ))}
              </ol>
            </details>
          )}
        </>
      )}
    </Sheet>
  );
}

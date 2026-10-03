/**
 * Options the cashier taps on a bill line: Large, Less sugar, Extra ginger.
 * Each option can change the price, the size (how much of the recipe), and add or
 * remove ingredients; the owner also picks which drinks offer it.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { formatQty } from '../lib/qty';
import {
  blankOption,
  describeOption,
  previewServing,
  toDraft,
  toOptionPayload,
  validateOption,
  type Dir,
  type OptionDraft,
  type OptionLine,
} from '../lib/options';
import type { Catalogue, Ingredient, Modifier } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';

type MenuRow = Catalogue['menu_items'][number];

let keySeq = 0;
const newKey = () => `opt-${++keySeq}`;
const unitWord = (i?: Ingredient) => (i ? (i.base_unit === 'piece' ? 'pcs' : i.base_unit) : '');

export function OptionsPanel({
  menu,
  ingredients,
  onChanged,
}: {
  menu: MenuRow[];
  ingredients: Ingredient[];
  onChanged(): void;
}) {
  const [mods, setMods] = useState<Modifier[] | null>(null);
  const [editing, setEditing] = useState<Modifier | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const byId = useMemo(() => Object.fromEntries(ingredients.map((i) => [i.id, i])), [ingredients]);
  const names = useMemo(() => Object.fromEntries(menu.map((m) => [m.id, m.name])), [menu]);

  async function load() {
    try {
      setMods(await api.get<Modifier[]>('/modifiers'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }
  // Reload with the menu: a new drink may have been given options from its own side.
  useEffect(() => {
    void load();
  }, [menu]);

  return (
    <section aria-labelledby="options-title">
      <h2 id="options-title">Options on the bill</h2>
      <p className="muted">Large, Less sugar, Extra ginger… The cashier taps them on a bill line.</p>
      {error && <p className="error">{error}</p>}
      <ul className="opt-list">
        {(mods ?? []).map((m) => {
          const on = m.menu_item_ids?.filter((id) => names[id]).map((id) => names[id]) ?? [];
          return (
            <li key={m.id}>
              <button onClick={() => setEditing(m)}>
                <span className="sop-name">
                  <strong>{m.name}</strong>
                  {!m.is_active && <span className="flag wait"> Switched off</span>}
                </span>
                <span className="sop-lines">{describeOption(m, byId)}</span>
                <span className={on.length ? 'sop-lines muted' : 'sop-lines warn-text'}>
                  {on.length ? `On: ${on.join(', ')}` : 'Not offered on any drink yet'}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <button onClick={() => setEditing('new')}>+ New option</button>
      {editing && (
        <OptionEditor
          option={editing === 'new' ? null : editing}
          menu={menu}
          ingredients={ingredients}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
            onChanged();
          }}
        />
      )}
    </section>
  );
}

function OptionEditor({
  option,
  menu,
  ingredients,
  onClose,
  onSaved,
}: {
  option: Modifier | null;
  menu: MenuRow[];
  ingredients: Ingredient[];
  onClose(): void;
  onSaved(): void;
}) {
  const [d, setD] = useState<OptionDraft>(option ? toDraft(option) : blankOption());
  // Drinks off the menu are not shown but keep their link: the set is sent back whole.
  const [offered, setOffered] = useState<Set<string>>(new Set(option?.menu_item_ids ?? []));
  const [savedId, setSavedId] = useState<string | null>(option?.id ?? null);
  const [previewId, setPreviewId] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);

  const byId = Object.fromEntries(ingredients.map((i) => [i.id, i]));
  const choices = ingredients.filter((i) => i.is_active || d.lines.some((l) => l.ingredient_id === i.id));
  const set = (patch: Partial<OptionDraft>) => {
    setD((x) => ({ ...x, ...patch }));
    setError(null);
  };
  const setLine = (key: string, patch: Partial<OptionLine>) =>
    set({ lines: d.lines.map((l) => (l.key === key ? { ...l, ...patch } : l)) });

  useEffect(() => {
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const withRecipe = menu.filter((m) => m.recipe && m.recipe.lines.length);
  const previewDrink =
    withRecipe.find((m) => m.id === previewId) ?? withRecipe.find((m) => offered.has(m.id)) ?? withRecipe[0];
  const preview = previewDrink ? previewServing(previewDrink.recipe!.lines, d, byId) : [];
  const problem = validateOption(d);

  async function save() {
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    try {
      const body = toOptionPayload(d);
      let id = savedId;
      if (id) await api.patch(`/modifiers/${id}`, { ...body, is_active: d.is_active });
      else {
        id = (await api.post<Modifier>('/modifiers', body)).id;
        setSavedId(id); // a retry after a failed second step must not create it twice
      }
      await api.put(`/modifiers/${id}/menu-items`, { menu_item_ids: [...offered] });
      onSaved();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const dirSelect = (value: Dir, onChange: (v: Dir) => void, label: string, words: [string, string]) => (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value as Dir)}>
      <option value="more">{words[0]}</option>
      <option value="less">{words[1]}</option>
    </select>
  );

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="option-title"
        tabIndex={-1}
        ref={dialog}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sheet-head">
          <h2 id="option-title">{option ? option.name : 'New option'}</h2>
          <button className="quiet" onClick={onClose}>
            Close
          </button>
        </header>

        <label>
          Name on the bill
          <input value={d.name} maxLength={40} placeholder="Large" onChange={(e) => set({ name: e.target.value })} />
        </label>

        <fieldset className="opt-row">
          <legend>Price</legend>
          {dirSelect(d.priceDir, (v) => set({ priceDir: v }), 'Price goes up or down', ['Adds', 'Takes off'])}
          <span aria-hidden="true">₹</span>
          <input
            aria-label="Price change in rupees"
            inputMode="decimal"
            placeholder="0"
            value={d.price}
            onChange={(e) => set({ price: e.target.value.replace(/[^0-9.]/g, '') })}
          />
        </fieldset>

        <label>
          Size (how much of the recipe)
          <input
            inputMode="decimal"
            value={d.scale}
            onChange={(e) => set({ scale: e.target.value.replace(/[^0-9.]/g, '') })}
          />
          <span className="muted hint">
            1 = same size, 1.5 = half as much again, 2 = double. Cups and lids (marked &quot;does not grow with
            size&quot;) stay at one.
          </span>
        </label>

        <fieldset>
          <legend>Ingredient changes per drink</legend>
          {d.lines.length === 0 && <p className="muted hint">None. Less sugar takes sugar off here.</p>}
          <ul className="recipe-lines opt-lines">
            {d.lines.map((l, i) => {
              const ing = byId[l.ingredient_id];
              return (
                <li key={l.key}>
                  <select
                    aria-label={`Ingredient ${i + 1}`}
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
                  {dirSelect(l.dir, (v) => setLine(l.key, { dir: v }), `More or less ${ing?.name ?? ''}`, ['+ more', '− less'])}
                  <input
                    aria-label={`How much ${ing?.name ?? `ingredient ${i + 1}`}`}
                    inputMode="decimal"
                    value={l.qty}
                    onChange={(e) => setLine(l.key, { qty: e.target.value.replace(/[^0-9.]/g, '') })}
                  />
                  <span className="unit">{unitWord(ing)}</span>
                  <button
                    className="quiet"
                    aria-label={`Remove ${ing?.name ?? 'row'}`}
                    onClick={() => set({ lines: d.lines.filter((x) => x.key !== l.key) })}
                  >
                    ✕
                  </button>
                </li>
              );
            })}
          </ul>
          <button
            onClick={() => set({ lines: [...d.lines, { key: newKey(), ingredient_id: '', dir: 'less', qty: '' }] })}
          >
            + Add ingredient change
          </button>
        </fieldset>

        <fieldset>
          <legend>Offered on</legend>
          <div className="opt-drinks">
            {menu.map((m) => (
              <label key={m.id} className="check">
                <input
                  type="checkbox"
                  checked={offered.has(m.id)}
                  onChange={(e) => {
                    const next = new Set(offered);
                    if (e.target.checked) next.add(m.id);
                    else next.delete(m.id);
                    setOffered(next);
                  }}
                />
                {m.name}
              </label>
            ))}
          </div>
        </fieldset>

        {previewDrink && (
          <div className="opt-preview" aria-live="polite">
            <label>
              One serving of
              <select value={previewDrink.id} onChange={(e) => setPreviewId(e.target.value)}>
                {withRecipe.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
              with {d.name.trim() || 'this option'} takes:
            </label>
            <table>
              <tbody>
                {preview.map((r) => (
                  <tr key={r.name}>
                    <th scope="row">{r.name}</th>
                    <td className="num muted">{formatQty(r.before, r.unit)}</td>
                    <td aria-hidden="true">→</td>
                    <td className={`num ${r.after !== r.before ? 'changed' : ''}`}>{formatQty(r.after, r.unit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {option && (
          <label className="check">
            <input type="checkbox" checked={d.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
            Switched on (cashiers can tap it)
          </label>
        )}
        <p className="muted hint">Bills already sold keep the option as it was when they were sold.</p>
        <div className="sheet-actions">
          <button className="primary" disabled={busy} onClick={() => void save()}>
            {option ? 'Save' : 'Add option'}
          </button>
          <button onClick={onClose}>Cancel</button>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

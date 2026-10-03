/** Menu items: price, category, GST rate and whether the price includes GST. */
import { useCallback, useEffect, useState } from 'react';
import { formatRate, formatRupees } from '../lib/gst';
import type { MenuItem, Modifier } from '../lib/types';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { Sheet } from './Sheet';
import { explainError } from './errors';
import { useSession } from './session';

// GST 2.0 slabs (22 Sept 2025). Cafe and restaurant service is 5%.
const RATES = [
  { bp: 500, label: '5% (tea, coffee, food served here)' },
  { bp: 1800, label: '18% (e.g. packaged drinks, some goods)' },
  { bp: 0, label: '0% (exempt)' },
  { bp: 4000, label: '40% (e.g. aerated sugary drinks)' },
];

type Draft = { name: string; category: string; price: string; gst_rate_bp: number; tax_inclusive: boolean; is_active: boolean };
const toDraft = (m: MenuItem): Draft => ({
  name: m.name,
  category: m.category,
  price: String(m.price_paise / 100),
  gst_rate_bp: m.gst_rate_bp,
  tax_inclusive: m.tax_inclusive,
  is_active: m.is_active,
});
const blank: Draft = { name: '', category: 'Tea', price: '', gst_rate_bp: 500, tax_inclusive: true, is_active: true };

export function MenuPrices() {
  const { reloadCatalogue } = useSession();
  const [items, setItems] = useState<MenuItem[] | null>(null);
  const [editing, setEditing] = useState<MenuItem | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await api.get<MenuItem[]>('/menu-items'));
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section aria-labelledby="menu-title">
      <h2 id="menu-title">Menu prices &amp; GST</h2>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {items === null && !error && <Loading />}
      <ul className="sop-list">
        {(items ?? []).map((m) => (
          <li key={m.id}>
            <button onClick={() => setEditing(m)}>
              <span className="sop-name">
                <strong>{m.name}</strong> <span className="muted">· {m.category}</span>
                {!m.is_active && <span className="flag wait"> Off the menu</span>}
              </span>
              <span className="sop-lines num">
                {formatRupees(m.price_paise)} · GST {formatRate(m.gst_rate_bp)}{' '}
                {m.tax_inclusive ? 'included' : 'added on top'}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <button onClick={() => setEditing('new')}>+ New menu item</button>
      {editing && (
        <MenuItemEditor
          item={editing === 'new' ? null : editing}
          categories={[...new Set((items ?? []).map((m) => m.category))]}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
            void reloadCatalogue();
          }}
        />
      )}
    </section>
  );
}

/** Add or edit a menu item. Also used by Recipes for "+ New drink". */
export function MenuItemEditor({
  item,
  categories,
  defaultCategory,
  recipeNext = false,
  onClose,
  onSaved,
}: {
  item: MenuItem | null;
  categories: string[];
  defaultCategory?: string;
  /** True when the recipe editor opens straight after adding (the Recipes flow). */
  recipeNext?: boolean;
  onClose(): void;
  onSaved(item: MenuItem): void;
}) {
  const [d, setD] = useState<Draft>(item ? toDraft(item) : { ...blank, category: defaultCategory ?? blank.category });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Options (Large, Less sugar) this drink offers. null until loaded.
  const [mods, setMods] = useState<Modifier[] | null>(null);
  const [offered, setOffered] = useState<Set<string>>(new Set());
  const [optionsTouched, setOptionsTouched] = useState(false);
  const [savedItem, setSavedItem] = useState<MenuItem | null>(item);

  useEffect(() => {
    api
      .get<Modifier[]>('/modifiers')
      .then((ms) => {
        setMods(ms);
        if (item) setOffered(new Set(ms.filter((m) => m.menu_item_ids?.includes(item.id)).map((m) => m.id)));
      })
      .catch(() => setMods([]));
  }, [item]);
  const set = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));
  const pricePaise = Math.round(Number(d.price) * 100);
  const valid = d.name.trim() && d.category.trim() && Number.isFinite(pricePaise) && pricePaise >= 0 && d.price !== '';

  async function save() {
    setBusy(true);
    setError(null);
    const body = {
      name: d.name.trim(),
      category: d.category.trim(),
      price_paise: pricePaise,
      gst_rate_bp: d.gst_rate_bp,
      tax_inclusive: d.tax_inclusive,
    };
    try {
      let saved = savedItem;
      if (saved) saved = await api.patch<MenuItem>(`/menu-items/${saved.id}`, { ...body, is_active: d.is_active });
      else {
        saved = await api.post<MenuItem>('/menu-items', body);
        setSavedItem(saved); // a retry after a failed second step must not add it twice
      }
      if (optionsTouched) await api.put(`/menu-items/${saved.id}/modifiers`, { modifier_ids: [...offered] });
      onSaved(saved);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={item ? item.name : 'New menu item'} onClose={onClose}>
      <label>
        Name
        <input value={d.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label>
        Category (menu tab)
        <input value={d.category} maxLength={40} list="menu-categories" onChange={(e) => set({ category: e.target.value })} />
        <datalist id="menu-categories">
          {categories.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </label>
      <label>
        Price (₹)
        <input inputMode="decimal" value={d.price} onChange={(e) => set({ price: e.target.value.replace(/[^0-9.]/g, '') })} />
      </label>
      <label>
        GST rate
        <select value={d.gst_rate_bp} onChange={(e) => set({ gst_rate_bp: Number(e.target.value) })}>
          {RATES.map((r) => (
            <option key={r.bp} value={r.bp}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      <label className="check">
        <input type="checkbox" checked={d.tax_inclusive} onChange={(e) => set({ tax_inclusive: e.target.checked })} />
        Price includes GST (customer pays exactly the menu price)
      </label>
      {item && (
        <label className="check">
          <input type="checkbox" checked={d.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
          On the menu
        </label>
      )}
      {mods && mods.length > 0 && (
        <fieldset>
          <legend>Options on the bill</legend>
          <div className="opt-drinks">
            {mods.map((m) => (
              <label key={m.id} className="check">
                <input
                  type="checkbox"
                  checked={offered.has(m.id)}
                  onChange={(e) => {
                    const next = new Set(offered);
                    if (e.target.checked) next.add(m.id);
                    else next.delete(m.id);
                    setOffered(next);
                    setOptionsTouched(true);
                  }}
                />
                {m.name}
                {!m.is_active && <span className="muted"> (switched off)</span>}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <p className="muted">
        GST only matters for a regular-GST shop. Changes reach each tablet when it next refreshes the menu; bills already
        printed keep their prices.
      </p>
      {!item && !recipeNext && (
        <p className="muted">After adding it, give it a recipe under Recipes, or its sales will not reduce stock.</p>
      )}
      <div className="sheet-actions">
        <button className="primary" disabled={!valid || busy} onClick={() => void save()}>
          {item ? 'Save' : recipeNext ? 'Next: the recipe' : 'Add to menu'}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  );
}

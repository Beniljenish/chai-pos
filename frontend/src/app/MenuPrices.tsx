/** Menu items: price, category, GST rate and whether the price includes GST. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { formatRate, formatRupees } from '../lib/gst';
import type { MenuItem } from '../lib/types';
import { api } from './apiClient';
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
      {error && <p className="error">{error}</p>}
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
        <ItemEditor
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

function ItemEditor({
  item,
  categories,
  onClose,
  onSaved,
}: {
  item: MenuItem | null;
  categories: string[];
  onClose(): void;
  onSaved(): void;
}) {
  const [d, setD] = useState<Draft>(item ? toDraft(item) : blank);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const set = (patch: Partial<Draft>) => setD((x) => ({ ...x, ...patch }));
  const pricePaise = Math.round(Number(d.price) * 100);
  const valid = d.name.trim() && d.category.trim() && Number.isFinite(pricePaise) && pricePaise >= 0 && d.price !== '';

  useEffect(() => {
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

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
      if (item) await api.patch(`/menu-items/${item.id}`, { ...body, is_active: d.is_active });
      else await api.post('/menu-items', body);
      onSaved();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="item-title"
        tabIndex={-1}
        ref={dialog}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="sheet-head">
          <h2 id="item-title">{item ? item.name : 'New menu item'}</h2>
          <button className="quiet" onClick={onClose}>
            Close
          </button>
        </header>
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
        <p className="muted">
          Only matters for a regular-GST shop. Changes reach each tablet when it next refreshes the menu; bills already
          printed keep their prices.
        </p>
        {!item && <p className="muted">After adding it, give it a recipe under Recipes, or its sales will not reduce stock.</p>}
        <div className="sheet-actions">
          <button className="primary" disabled={!valid || busy} onClick={() => void save()}>
            {item ? 'Save' : 'Add to menu'}
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

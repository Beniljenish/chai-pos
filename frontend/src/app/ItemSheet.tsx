/** One ingredient: stock-in, opening count, and its full history. */
import { useEffect, useState } from 'react';
import { HttpError } from '../lib/api';
import { formatDelta, formatQty, packsPayload, packsToBase } from '../lib/qty';
import type { Ingredient, LedgerRow, StockRow } from '../lib/types';
import { buyUnit, fromBaseQty, toBaseQty } from '../lib/reports';
import { api } from './apiClient';
import { Sheet } from './Sheet';
import { explainError } from './errors';
import { PackEntry } from './PackEntry';

const REASON: Record<LedgerRow['reason'], string> = {
  opening: 'Opening count',
  stock_in: 'Stock in',
  sale: 'Sold',
  prep_in: 'Batch made',
  prep_out: 'Used in batch',
  void: 'Bill cancelled',
  wastage: 'Wasted',
  count_adjustment: 'Count correction',
};

type Mode = 'history' | 'stock-in' | 'opening';

interface Props {
  row: StockRow;
  ingredient: Ingredient;
  onClose(): void;
  onChanged(): void;
}

export function ItemSheet({ row, ingredient, onClose, onChanged }: Props) {
  const [mode, setMode] = useState<Mode>('history');
  const [ledger, setLedger] = useState<LedgerRow[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loose, setLoose] = useState('');
  const [cost, setCost] = useState('');
  const [supplier, setSupplier] = useState('');
  const [confirmLarge, setConfirmLarge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const unit = ingredient.base_unit;
  const canStockIn = ingredient.kind === 'raw';

  useEffect(() => {
    if (mode !== 'history') return;
    api
      .get<LedgerRow[]>(`/stock/${ingredient.id}/ledger?limit=50`)
      .then(setLedger)
      .catch((e) => setError(explainError(e)));
  }, [mode, ingredient.id, row.on_hand]);

  function start(next: Mode) {
    setCounts({});
    setLoose('');
    setCost('');
    setSupplier('');
    setConfirmLarge(null);
    setError(null);
    setMode(next);
  }

  const total = packsToBase(ingredient.pack_units, counts, Number(loose) || 0);

  async function save(confirm = false) {
    setBusy(true);
    setError(null);
    const body = {
      ingredient_id: ingredient.id,
      packs: packsPayload(counts),
      loose_qty: String(Number(loose) || 0),
    };
    try {
      if (mode === 'opening') {
        await api.post('/stock/opening', body);
      } else {
        await api.post('/stock-in', {
          ...body,
          cost_paise: Math.round((Number(cost) || 0) * 100),
          supplier: supplier.trim(),
          confirm_large: confirm,
        });
      }
      onChanged();
      start('history');
    } catch (e) {
      const d = e instanceof HttpError ? (e.detail as { needs?: string; typical?: string }) : null;
      if (e instanceof HttpError && e.status === 409 && d?.needs === 'confirm_large') {
        setConfirmLarge(
          `${formatQty(total, unit)} is more than 3 times a usual delivery (${formatQty(d.typical ?? 0, unit)}). Is that right?`,
        );
      } else {
        setError(explainError(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      title={ingredient.name}
      sub={<p className={`num sheet-qty ${row.is_negative ? 'neg' : ''}`}>{formatQty(row.on_hand, unit)} on hand</p>}
      onClose={onClose}
    >

      {mode === 'history' && (
        <>
          <div className="sheet-actions">
            {canStockIn && (
              <button className="primary" onClick={() => start('stock-in')}>
                Stock in
              </button>
            )}
            {!row.has_opening && <button onClick={() => start('opening')}>Enter opening count</button>}
          </div>
          {!canStockIn && (
            <p className="muted">Made here: it goes up when a batch is logged, not by stock-in.</p>
          )}
          <ReorderLevel ingredient={ingredient} onSaved={onChanged} />
          <CountFrequency ingredient={ingredient} onSaved={onChanged} />
          <h3>History</h3>
          {ledger === null ? (
            <p className="muted">Loading…</p>
          ) : ledger.length === 0 ? (
            <p className="empty">No movements yet.</p>
          ) : (
            <ul className="ledger">
              {ledger.map((l) => (
                <li key={l.id}>
                  <span>{REASON[l.reason] ?? l.reason}</span>
                  <span className="muted num">
                    {new Intl.DateTimeFormat('en-IN', {
                      timeZone: 'Asia/Kolkata',
                      day: 'numeric',
                      month: 'short',
                      hour: 'numeric',
                      minute: '2-digit',
                    }).format(new Date(l.created_at))}
                  </span>
                  <span className={`num right ${Number(l.qty_delta) < 0 ? '' : 'plus'}`}>
                    {formatDelta(l.qty_delta, unit)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {mode !== 'history' && (
        <div className="sheet-form">
          <h3>{mode === 'opening' ? 'Opening count' : 'Stock in'}</h3>
          {mode === 'opening' && (
            <p className="warn">
              Count what is on the shelf right now. This is entered <strong>once</strong>; after this, mistakes are
              corrected by the day-end count, so every change keeps a reason.
            </p>
          )}
          <PackEntry ingredient={ingredient} counts={counts} loose={loose} onCounts={setCounts} onLoose={setLoose} />
          {mode === 'stock-in' && (
            <>
              <label>
                Paid (₹, optional)
                <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value.replace(/[^0-9.]/g, ''))} />
              </label>
              <label>
                Supplier (optional)
                <input value={supplier} maxLength={80} onChange={(e) => setSupplier(e.target.value)} />
              </label>
            </>
          )}
          {confirmLarge ? (
            <div className="warn" role="alert">
              <p>{confirmLarge}</p>
              <div className="sheet-actions">
                <button className="primary" disabled={busy} onClick={() => save(true)}>
                  Yes, save it
                </button>
                <button onClick={() => setConfirmLarge(null)}>Let me fix it</button>
              </div>
            </div>
          ) : (
            <div className="sheet-actions">
              <button
                className="primary"
                disabled={busy || (mode === 'stock-in' && total <= 0)}
                onClick={() => save(false)}
              >
                {mode === 'opening' ? `Save count: ${formatQty(total, unit)}` : `Add ${formatQty(total, unit)}`}
              </button>
              <button onClick={() => start('history')}>Cancel</button>
            </div>
          )}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  );
}

/** Phase 7: below this, Stock marks the item and Purchases suggests ordering it. */
function ReorderLevel({ ingredient, onSaved }: { ingredient: Ingredient; onSaved(): void }) {
  const unit = ingredient.base_unit;
  const initial = ingredient.reorder_level ? fromBaseQty(ingredient.reorder_level, unit) : '';
  const [value, setValue] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const base = value.trim() === '' ? null : toBaseQty(value, unit);
  async function save() {
    try {
      await api.patch(`/ingredients/${ingredient.id}`, { reorder_level: base });
      setSaved(value);
      setError(null);
      onSaved();
    } catch (e) {
      setError(explainError(e));
    }
  }
  return (
    <div className="reorder-level">
      <label>
        Reorder below ({buyUnit(unit)})
        <input inputMode="decimal" value={value} placeholder="not set" onChange={(e) => setValue(e.target.value)} />
      </label>
      <button disabled={value === saved || base === ''} onClick={() => void save()}>
        Save
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

/** Phase 10.3: "every shift" adds the item to the count at each shift change. */
function CountFrequency({ ingredient, onSaved }: { ingredient: Ingredient; onSaved(): void }) {
  const [value, setValue] = useState(ingredient.count_frequency);
  const [error, setError] = useState<string | null>(null);
  async function save(next: Ingredient['count_frequency']) {
    const before = value;
    setValue(next);
    try {
      await api.patch(`/ingredients/${ingredient.id}`, { count_frequency: next });
      setError(null);
      onSaved();
    } catch (e) {
      setValue(before);
      setError(explainError(e));
    }
  }
  return (
    <div className="count-frequency">
      <span className="muted">Count it</span>
      <div className="segmented" role="radiogroup" aria-label="How often to count it">
        {(
          [
            ['shift', 'Every shift'],
            ['daily', 'Every day'],
            ['weekly', 'Weekly'],
          ] as const
        ).map(([id, label]) => (
          <button key={id} role="radio" aria-checked={value === id} onClick={() => void save(id)}>
            {label}
          </button>
        ))}
      </div>
      {value === 'shift' && (
        <p className="muted">Counted at each shift change as well as at day end, so a gap shows which shift it was in.</p>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

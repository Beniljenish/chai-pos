/**
 * Owner, Manage → Purchases (README, "Phase 7"): suppliers, and purchase orders.
 * "Fill from reorder levels" proposes what is running low; receiving an order
 * records what actually came and enters it as stock.
 */
import { useCallback, useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { dayTime } from '../lib/health';
import { formatQty, type BaseUnit } from '../lib/qty';
import { buyUnit, fromBaseQty, toBaseQty } from '../lib/reports';
import type { Ingredient } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { Sheet } from './Sheet';
import { Loading, LoadError } from './Status';

interface Supplier {
  id: string;
  name: string;
  phone: string;
  note: string;
  is_active: boolean;
}

interface PoLine {
  id: string;
  ingredient_id: string;
  name: string;
  base_unit: BaseUnit;
  qty: string;
  expected_cost_paise: number;
  received_qty: string | null;
  cost_paise: number | null;
}

interface Po {
  id: string;
  supplier_id: string;
  supplier_name: string;
  status: 'open' | 'received' | 'cancelled';
  note: string;
  created_at: string;
  expected_total_paise: number;
  received_total_paise: number;
  lines: PoLine[];
}

interface DraftLine {
  ingredientId: string;
  qty: string; // in the buying unit (L, kg, pcs)
  rupees: string;
}

const rupeesOk = (v: string) => /^\d{0,7}(\.\d{0,2})?$/.test(v);
const paise = (rupees: string) => Math.round(Number(rupees || '0') * 100);
const STATUS = { open: 'Ordered', received: 'Received', cancelled: 'Cancelled' };

export function PurchasesScreen() {
  const [suppliers, setSuppliers] = useState<Supplier[] | null>(null);
  const [orders, setOrders] = useState<Po[] | null>(null);
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<'supplier' | 'order' | { po: Po } | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, o, i] = await Promise.all([
        api.get<Supplier[]>('/suppliers'),
        api.get<Po[]>('/purchase-orders'),
        api.get<Ingredient[]>('/ingredients'),
      ]);
      setSuppliers(s);
      setOrders(o);
      setIngredients(i.filter((x) => x.kind === 'raw' && x.is_active));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const done = () => {
    setSheet(null);
    void load();
  };

  return (
    <section>
      <header className="manage-head">
        <h1>Purchases</h1>
        <button className="primary" disabled={!suppliers?.length} onClick={() => setSheet('order')}>
          + Order
        </button>
      </header>
      <p className="muted">
        Order from a supplier, then receive what actually came: it goes into stock at the price you paid.
      </p>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {orders === null && !error && <Loading />}

      {orders && (
        <>
          <h2>Orders</h2>
          {orders.length === 0 ? (
            <div className="empty-card">
              <p>
                <strong>No orders yet.</strong> {suppliers?.length ? 'Tap + Order.' : 'Add a supplier first.'}
              </p>
            </div>
          ) : (
            <ul className="sop-list po-list">
              {orders.map((po) => (
                <li key={po.id}>
                  <button onClick={() => setSheet({ po })}>
                    <strong>{po.supplier_name}</strong> <span className="muted">{dayTime(po.created_at)}</span>
                    <span className={`flag ${po.status === 'open' ? 'wait' : po.status === 'received' ? 'ok' : ''}`}>
                      {STATUS[po.status]}
                    </span>
                    <br />
                    <span className="muted">
                      {po.lines.map((l) => `${l.name} ${formatQty(l.received_qty ?? l.qty, l.base_unit)}`).join(', ')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {suppliers && (
        <>
          <div className="manage-head">
            <h2>Suppliers</h2>
            <button className="quiet" onClick={() => setSheet('supplier')}>
              + Supplier
            </button>
          </div>
          <ul className="sop-list">
            {suppliers.map((s) => (
              <li key={s.id}>
                <strong>{s.name}</strong> {s.phone && <span className="muted num">{s.phone}</span>}
                {s.note && <span className="muted"> · {s.note}</span>}
              </li>
            ))}
          </ul>
        </>
      )}

      {sheet === 'supplier' && <SupplierSheet onClose={() => setSheet(null)} onDone={done} />}
      {sheet === 'order' && suppliers && (
        <OrderSheet suppliers={suppliers.filter((s) => s.is_active)} ingredients={ingredients} onClose={() => setSheet(null)} onDone={done} />
      )}
      {sheet && typeof sheet === 'object' && <PoSheet po={sheet.po} onClose={() => setSheet(null)} onDone={done} />}
    </section>
  );
}

function SupplierSheet({ onClose, onDone }: { onClose(): void; onDone(): void }) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  async function save() {
    try {
      await api.post('/suppliers', { name: name.trim(), phone: phone.trim(), note: note.trim() });
      onDone();
    } catch (e) {
      setError(explainError(e));
    }
  }
  return (
    <Sheet title="New supplier" onClose={onClose}>
      <label>
        Name
        <input value={name} maxLength={80} autoFocus onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Phone (optional)
        <input inputMode="tel" value={phone} maxLength={15} onChange={(e) => setPhone(e.target.value)} />
      </label>
      <label>
        Note (optional)
        <input value={note} maxLength={200} placeholder="Delivers Mon and Thu" onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="sheet-actions">
        <button className="primary" disabled={!name.trim()} onClick={() => void save()}>
          Add supplier
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

function OrderSheet({
  suppliers,
  ingredients,
  onClose,
  onDone,
}: {
  suppliers: Supplier[];
  ingredients: Ingredient[];
  onClose(): void;
  onDone(): void;
}) {
  const [supplierId, setSupplierId] = useState(suppliers[0]?.id ?? '');
  const [note, setNote] = useState('');
  const [lines, setLines] = useState<DraftLine[]>([{ ingredientId: ingredients[0]?.id ?? '', qty: '', rupees: '' }]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const byId = new Map(ingredients.map((i) => [i.id, i]));
  const unitOf = (id: string) => byId.get(id)?.base_unit ?? 'piece';
  const valid = supplierId && lines.length > 0 && lines.every((l) => byId.has(l.ingredientId) && Number(toBaseQty(l.qty, unitOf(l.ingredientId))) > 0);

  async function suggest() {
    try {
      const r = await api.get<{ lines: { ingredient_id: string; base_unit: BaseUnit; qty: string; expected_cost_paise: number }[] }>(
        '/purchase-orders/suggest',
      );
      if (r.lines.length === 0) return setError('Nothing is below its reorder level.');
      setError(null);
      setLines(
        r.lines.map((l) => ({
          ingredientId: l.ingredient_id,
          qty: fromBaseQty(l.qty, l.base_unit),
          rupees: l.expected_cost_paise ? String(l.expected_cost_paise / 100) : '',
        })),
      );
    } catch (e) {
      setError(explainError(e));
    }
  }

  async function save() {
    setBusy(true);
    try {
      await api.post('/purchase-orders', {
        supplier_id: supplierId,
        note: note.trim(),
        lines: lines.map((l) => ({
          ingredient_id: l.ingredientId,
          qty: toBaseQty(l.qty, unitOf(l.ingredientId)),
          expected_cost_paise: paise(l.rupees),
        })),
      });
      onDone();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const set = (k: number, patch: Partial<DraftLine>) => setLines((ls) => ls.map((l, i) => (i === k ? { ...l, ...patch } : l)));
  return (
    <Sheet title="New order" onClose={onClose}>
      <label>
        Supplier
        <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <button className="quiet" onClick={() => void suggest()}>
        Fill from reorder levels
      </button>
      <ul className="po-lines">
        {lines.map((l, k) => (
          <li key={k}>
            <select aria-label={`Item ${k + 1}`} value={l.ingredientId} onChange={(e) => set(k, { ingredientId: e.target.value })}>
              {ingredients.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
            <label>
              Qty ({buyUnit(unitOf(l.ingredientId))})
              <input inputMode="decimal" value={l.qty} onChange={(e) => set(k, { qty: e.target.value })} />
            </label>
            <label>
              Expected ₹
              <input inputMode="decimal" value={l.rupees} onChange={(e) => rupeesOk(e.target.value) && set(k, { rupees: e.target.value })} />
            </label>
            {lines.length > 1 && (
              <button className="quiet" onClick={() => setLines((ls) => ls.filter((_, i) => i !== k))} aria-label={`Remove item ${k + 1}`}>
                Remove
              </button>
            )}
          </li>
        ))}
      </ul>
      <button className="quiet" onClick={() => setLines((ls) => [...ls, { ingredientId: ingredients[0]?.id ?? '', qty: '', rupees: '' }])}>
        + Another item
      </button>
      <label>
        Note (optional)
        <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="sheet-actions">
        <button className="primary" disabled={!valid || busy} onClick={() => void save()}>
          Save order ({formatRupees(lines.reduce((a, l) => a + paise(l.rupees), 0))})
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

function PoSheet({ po, onClose, onDone }: { po: Po; onClose(): void; onDone(): void }) {
  // What came: prefilled with what was ordered, at the expected price.
  const [got, setGot] = useState(() =>
    po.lines.map((l) => ({ qty: fromBaseQty(l.qty, l.base_unit), rupees: l.expected_cost_paise ? String(l.expected_cost_paise / 100) : '' })),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const open = po.status === 'open';
  const valid = got.every((g, k) => toBaseQty(g.qty || '0', po.lines[k].base_unit) !== '');

  async function act(path: 'receive' | 'cancel') {
    setBusy(true);
    try {
      await api.post(
        `/purchase-orders/${po.id}/${path}`,
        path === 'receive'
          ? {
              lines: po.lines.map((l, k) => ({
                line_id: l.id,
                qty: toBaseQty(got[k].qty || '0', l.base_unit),
                cost_paise: paise(got[k].rupees),
              })),
            }
          : {},
      );
      onDone();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={`${po.supplier_name}: ${STATUS[po.status]}`} onClose={onClose}>
      <p className="muted">
        Ordered {dayTime(po.created_at)}
        {po.note && ` · ${po.note}`}
      </p>
      <ul className="po-lines">
        {po.lines.map((l, k) => (
          <li key={l.id}>
            <strong>{l.name}</strong>
            <span className="muted">
              ordered {formatQty(l.qty, l.base_unit)}
              {l.expected_cost_paise ? `, ${formatRupees(l.expected_cost_paise)}` : ''}
            </span>
            {open ? (
              <>
                <label>
                  Came ({buyUnit(l.base_unit)})
                  <input
                    inputMode="decimal"
                    value={got[k].qty}
                    onChange={(e) => setGot((g) => g.map((x, i) => (i === k ? { ...x, qty: e.target.value } : x)))}
                  />
                </label>
                <label>
                  Paid ₹
                  <input
                    inputMode="decimal"
                    value={got[k].rupees}
                    onChange={(e) =>
                      rupeesOk(e.target.value) && setGot((g) => g.map((x, i) => (i === k ? { ...x, rupees: e.target.value } : x)))
                    }
                  />
                </label>
              </>
            ) : (
              l.received_qty !== null && (
                <span>
                  came {formatQty(l.received_qty, l.base_unit)}
                  {l.cost_paise ? `, paid ${formatRupees(l.cost_paise)}` : ''}
                </span>
              )
            )}
          </li>
        ))}
      </ul>
      {error && <p className="error">{error}</p>}
      {open && (
        <div className="sheet-actions">
          <button className="primary" disabled={!valid || busy} onClick={() => void act('receive')}>
            Receive into stock
          </button>
          <button className="quiet" disabled={busy} onClick={() => void act('cancel')}>
            Cancel order
          </button>
        </div>
      )}
    </Sheet>
  );
}

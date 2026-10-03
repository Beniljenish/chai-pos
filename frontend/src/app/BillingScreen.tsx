import { useMemo, useState } from 'react';
import { buildLines, priceLines, saveBill, type CartLine, type PaymentMode } from '../lib/billing';
import type { LocalBill } from '../lib/db';
import { db } from '../lib/db';
import { formatRupees, GstError } from '../lib/gst';
import { formatPriceDelta } from '../lib/options';
import { Receipt } from './Receipt';
import { PAYMENT_LABELS } from '../lib/sales';
import { shiftsOn } from '../lib/shift';
import { StartShiftSheet } from './ShiftUI';
import { useSession } from './session';

interface Line extends CartLine {
  key: string;
}

const PAYMENT_MODES: { mode: PaymentMode; label: string }[] = [
  { mode: 'cash', label: 'Cash' },
  { mode: 'upi', label: 'UPI' },
  { mode: 'card', label: 'Card' },
];

export function BillingScreen() {
  const { catalogue, device, worker, user, shift } = useSession();
  const [askShift, setAskShift] = useState(false);
  const [cart, setCart] = useState<Line[]>([]);
  const [category, setCategory] = useState<string | null>(null);
  const [payment, setPayment] = useState<PaymentMode>('cash');
  const [saved, setSaved] = useState<LocalBill | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tillOpen, setTillOpen] = useState(false); // phones: the till is a bottom sheet

  const items = useMemo(() => catalogue?.menu_items.filter((m) => m.is_active) ?? [], [catalogue]);
  const categories = useMemo(() => [...new Set(items.map((i) => i.category))], [items]);
  const activeCategory = category ?? categories[0] ?? null;
  const modifiers = useMemo(() => new Map(catalogue?.modifiers.map((m) => [m.id, m]) ?? []), [catalogue]);
  const itemsById = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);

  const totals = useMemo(() => {
    if (!catalogue || cart.length === 0) return null;
    try {
      return priceLines(buildLines(cart, catalogue), catalogue.shop.gst_type);
    } catch {
      return null;
    }
  }, [cart, catalogue]);

  if (!catalogue) {
    return (
      <main className="centered">
        <div className="panel">
          <h1>No menu on this tablet yet</h1>
          <p>Connect to the internet once so the tablet can download the menu. After that it works offline.</p>
        </div>
      </main>
    );
  }

  function add(menuItemId: string) {
    setCart((c) => {
      const same = c.find((l) => l.menuItemId === menuItemId && l.modifierIds.length === 0);
      if (same) return c.map((l) => (l === same ? { ...l, qty: l.qty + 1 } : l));
      return [...c, { key: crypto.randomUUID(), menuItemId, qty: 1, modifierIds: [] }];
    });
  }

  function setQty(key: string, qty: number) {
    setCart((c) => (qty <= 0 ? c.filter((l) => l.key !== key) : c.map((l) => (l.key === key ? { ...l, qty } : l))));
  }

  function toggleModifier(key: string, modifierId: string) {
    setCart((c) =>
      c.map((l) =>
        l.key !== key
          ? l
          : {
              ...l,
              modifierIds: l.modifierIds.includes(modifierId)
                ? l.modifierIds.filter((m) => m !== modifierId)
                : [...l.modifierIds, modifierId],
            },
      ),
    );
  }

  async function save(shiftId = shift?.id) {
    if (!device || !catalogue || cart.length === 0) return;
    // The drawer must have a shift, so this cash is counted against something.
    if (shiftsOn(catalogue.shop.cash_shifts) && !shiftId) return setAskShift(true);
    setSaving(true);
    setError(null);
    try {
      const bill = await saveBill({
        db,
        deviceId: device.id,
        deviceCode: device.code,
        catalogue,
        cart: cart.map(({ menuItemId, qty, modifierIds }) => ({ menuItemId, qty, modifierIds })),
        paymentMode: payment,
        cashierId: user?.id,
        shiftId: shiftsOn(catalogue.shop.cash_shifts) ? shiftId : undefined,
      });
      setSaved(bill);
      setCart([]);
      setPayment('cash');
      setTillOpen(false);
      void worker?.kick(); // send now if online; otherwise it waits in the outbox
    } catch (e) {
      setError(e instanceof GstError ? e.message : 'Could not save the bill. Nothing was charged.');
    } finally {
      setSaving(false);
    }
  }

  const itemCount = cart.reduce((n, l) => n + l.qty, 0);

  return (
    <div className="billing">
      {shift && user && shift.openedById !== user.id && shiftsOn(catalogue?.shop.cash_shifts) && (
        <p className="shift-note" role="note">
          Billing into {shift.openedByName}&apos;s shift. Taking over the drawer? End it under Today first.
        </p>
      )}
      <section className="menu" aria-label="Menu">
        {categories.length > 1 && (
          <nav className="categories" aria-label="Categories">
            {categories.map((c) => (
              <button key={c} aria-pressed={c === activeCategory} onClick={() => setCategory(c)}>
                {c}
              </button>
            ))}
          </nav>
        )}
        <div className="grid">
          {items
            .filter((i) => i.category === activeCategory)
            .map((i) => {
              const inCart = cart.filter((l) => l.menuItemId === i.id).reduce((n, l) => n + l.qty, 0);
              return (
                <button key={i.id} className="tile" onClick={() => add(i.id)}>
                  <span className="tile-name">{i.name}</span>
                  <span className="tile-price">{formatRupees(i.price_paise)}</span>
                  {inCart > 0 && <span className="tile-count" aria-label={`${inCart} in bill`}>{inCart}</span>}
                </button>
              );
            })}
        </div>
      </section>

      <aside className={`till ${tillOpen ? 'open' : ''}`} aria-label="Current bill">
        <div className="till-bar">
          <button className="till-handle" onClick={() => setTillOpen((o) => !o)} aria-expanded={tillOpen}>
            <span>{itemCount ? `${itemCount} item${itemCount > 1 ? 's' : ''}` : 'Empty bill'}</span>
            <strong className="num">{formatRupees(totals?.total ?? 0)}</strong>
          </button>
          {/* Phones: the usual sale (a tea, paid as before) without opening the bill. */}
          {!tillOpen && itemCount > 0 && totals && (
            <button className="primary quick-save" disabled={saving} onClick={() => void save()}>
              Save · {PAYMENT_LABELS[payment]}
            </button>
          )}
        </div>

        <div className="till-body">
          {cart.length === 0 ? (
            <p className="empty">Tap an item to start a bill.</p>
          ) : (
            <ul className="lines">
              {cart.map((l, idx) => {
                const item = itemsById.get(l.menuItemId);
                if (!item) return null;
                const lineTotal = totals?.lines[idx]?.total ?? 0;
                return (
                  <li key={l.key}>
                    <div className="line-top">
                      <span className="line-name">{item.name}</span>
                      <span className="num">{formatRupees(lineTotal)}</span>
                    </div>
                    <div className="line-controls">
                      <div className="stepper">
                        <button onClick={() => setQty(l.key, l.qty - 1)} aria-label={`One less ${item.name}`}>−</button>
                        <span className="num" aria-live="polite">{l.qty}</span>
                        <button onClick={() => setQty(l.key, l.qty + 1)} aria-label={`One more ${item.name}`}>+</button>
                      </div>
                      {item.modifier_ids.map((mid) => {
                        const m = modifiers.get(mid);
                        if (!m || !m.is_active) return null;
                        return (
                          <button
                            key={mid}
                            className="chip"
                            aria-pressed={l.modifierIds.includes(mid)}
                            onClick={() => toggleModifier(l.key, mid)}
                          >
                            {m.name}
                            {m.price_delta_paise ? ` ${formatPriceDelta(m.price_delta_paise)}` : ''}
                          </button>
                        );
                      })}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="till-foot">
            {totals && catalogue.shop.gst_type === 'regular' && totals.cgst > 0 && (
              <p className="tax-note num">
                Includes GST {formatRupees(totals.cgst + totals.sgst)}
              </p>
            )}
            <p className="total">
              <span>Total</span>
              <strong className="num">{formatRupees(totals?.total ?? 0)}</strong>
            </p>
            <div className="payment" role="radiogroup" aria-label="Payment">
              {PAYMENT_MODES.map(({ mode, label }) => (
                <button key={mode} role="radio" aria-checked={payment === mode} onClick={() => setPayment(mode)}>
                  {label}
                </button>
              ))}
            </div>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="primary save" onClick={() => void save()} disabled={saving || cart.length === 0}>
              {saving ? 'Saving…' : 'Save and print'}
            </button>
          </div>
        </div>
      </aside>

      {saved && <Receipt bill={saved} onClose={() => setSaved(null)} autoPrint />}
      {askShift && (
        <StartShiftSheet
          onClose={() => setAskShift(false)}
          onStarted={(s) => {
            setAskShift(false);
            void save(s.id); // the bill that asked for the shift goes into it
          }}
        />
      )}
    </div>
  );
}

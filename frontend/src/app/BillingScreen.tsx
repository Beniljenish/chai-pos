import { useMemo, useState } from 'react';
import { buildLines, priceLines, saveBill, type CartLine, type PaymentMode } from '../lib/billing';
import type { LocalBill } from '../lib/db';
import { db } from '../lib/db';
import { formatRupees, GstError } from '../lib/gst';
import { formatPriceDelta } from '../lib/options';
import { OnlinePayment } from './OnlinePayment';
import { Receipt } from './Receipt';
import { PAYMENT_LABELS } from '../lib/sales';
import { shiftsOn } from '../lib/shift';
import { StartShiftSheet } from './ShiftUI';
import { CustomerSheet, DiscountSheet, SplitSheet, type SplitChoice } from './TillExtras';
import type { BillCustomer, PaymentPart } from '../lib/types';
import { useSession } from './session';

interface Line extends CartLine {
  key: string;
}

const PAYMENT_MODES: { mode: PaymentMode; label: string }[] = [
  { mode: 'cash', label: 'Cash' },
  { mode: 'upi', label: 'UPI' },
  { mode: 'card', label: 'Card' },
  { mode: 'split', label: 'Split' },
  { mode: 'credit', label: 'Credit' },
];

/** The payment parts for a split or part-credit bill, from the cashier's choice. */
function partsFor(mode: PaymentMode, total: number, split: SplitChoice | null, paidNow: number): PaymentPart[] | undefined {
  if (mode === 'split' && split) return [{ mode: 'cash', paise: split.cashPaise }, { mode: split.other, paise: total - split.cashPaise }];
  if (mode === 'credit' && paidNow > 0) return [{ mode: 'cash', paise: paidNow }, { mode: 'credit', paise: total - paidNow }];
  return undefined;
}

export function BillingScreen() {
  const { catalogue, device, worker, user, shift } = useSession();
  const [askShift, setAskShift] = useState(false);
  const [cart, setCart] = useState<Line[]>([]);
  const [category, setCategory] = useState<string | null>(null);
  const [payment, setPayment] = useState<PaymentMode>('cash');
  const [saved, setSaved] = useState<LocalBill | null>(null);
  // Razorpay (test mode): offered only when the server has keys and for UPI/card.
  const [online, setOnline] = useState(false);
  const [collect, setCollect] = useState<{ bill: LocalBill; method: 'upi' | 'card' } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tillOpen, setTillOpen] = useState(false); // phones: the till is a bottom sheet
  // Phase 6: discount, split, customer (and credit).
  const [billDiscount, setBillDiscount] = useState(0);
  const [discountReason, setDiscountReason] = useState('');
  const [split, setSplit] = useState<SplitChoice | null>(null);
  const [customer, setCustomer] = useState<BillCustomer | null>(null);
  const [paidNow, setPaidNow] = useState(0);
  const [sheet, setSheet] = useState<'discount' | 'split' | 'customer' | 'credit' | null>(null);

  const items = useMemo(() => catalogue?.menu_items.filter((m) => m.is_active) ?? [], [catalogue]);
  const categories = useMemo(() => [...new Set(items.map((i) => i.category))], [items]);
  const activeCategory = category ?? categories[0] ?? null;
  const modifiers = useMemo(() => new Map(catalogue?.modifiers.map((m) => [m.id, m]) ?? []), [catalogue]);
  const itemsById = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);

  const totals = useMemo(() => {
    if (!catalogue || cart.length === 0) return null;
    try {
      return priceLines(buildLines(cart, catalogue), catalogue.shop.gst_type, billDiscount);
    } catch {
      return null;
    }
  }, [cart, catalogue, billDiscount]);

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
        paymentMode: payment === 'credit' && paidNow > 0 ? 'split' : payment,
        paymentParts: partsFor(payment, totals?.total ?? 0, split, paidNow),
        billDiscountPaise: billDiscount,
        discountReason,
        customer: customer ?? undefined,
        cashierId: user?.id,
        shiftId: shiftsOn(catalogue.shop.cash_shifts) ? shiftId : undefined,
      });
      const onlineNow = canCollectOnline && online;
      if (onlineNow) setCollect({ bill, method: payment as 'upi' | 'card' });
      else setSaved(bill);
      setCart([]);
      setPayment('cash');
      setBillDiscount(0);
      setDiscountReason('');
      setSplit(null);
      setCustomer(null);
      setPaidNow(0);
      setOnline(false);
      setTillOpen(false);
      void worker?.kick(); // send now if online; otherwise it waits in the outbox
    } catch (e) {
      // saveBill's own refusals (parts that do not add up, credit with no customer)
      // are written for the cashier; anything else is a storage failure.
      const ours = e instanceof Error && /add up|customer|empty/.test(e.message);
      setError(e instanceof GstError || ours ? (e as Error).message : 'Could not save the bill. Nothing was charged.');
    } finally {
      setSaving(false);
    }
  }

  const itemCount = cart.reduce((n, l) => n + l.qty, 0);
  // Phase 6: what the bill is worth before discounts (the cashier's limit is a
  // share of this), and whether the chosen payment is complete.
  const grossPaise = totals?.lines.reduce((a, l) => a + l.gross, 0) ?? 0;
  const lineDiscounts = Object.fromEntries(cart.map((l) => [l.key, l.discountPaise ?? 0]));
  const discountTotal = billDiscount + cart.reduce((a, l) => a + (l.discountPaise ?? 0), 0);
  const splitBad = payment === 'split' && (!split || !totals || split.cashPaise >= totals.total);
  const creditBad = payment === 'credit' && (!customer || (totals !== null && paidNow >= totals.total));
  const paymentNote =
    payment === 'split' && split && totals && !splitBad
      ? `Cash ${formatRupees(split.cashPaise)} + ${split.other === 'upi' ? 'UPI' : 'Card'} ${formatRupees(totals.total - split.cashPaise)}`
      : payment === 'credit' && customer && totals && !creditBad
        ? `${formatRupees(totals.total - paidNow)} on ${customer.name}'s khata${paidNow ? `, ${formatRupees(paidNow)} cash now` : ''}`
        : null;
  const canCollectOnline = Boolean(catalogue?.shop.online_payments) && (payment === 'upi' || payment === 'card');

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
              {canCollectOnline && online ? 'Collect' : 'Save'} · {PAYMENT_LABELS[payment]}
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
            <div className="till-extras">
              <button className="quiet" disabled={cart.length === 0} onClick={() => setSheet('discount')}>
                {discountTotal ? `Discount −${formatRupees(totals?.discount ?? discountTotal)}` : 'Discount'}
              </button>
              <button className="quiet" onClick={() => setSheet('customer')}>
                {customer ? `Customer: ${customer.name}` : '+ Customer'}
              </button>
            </div>
            {discountTotal > 0 && !totals && (
              <p className="error" role="alert">
                The discount is more than the bill now.{' '}
                <button className="quiet" onClick={() => setBillDiscount(0)}>
                  Remove it
                </button>
              </p>
            )}
            <p className="total">
              <span>Total</span>
              <strong className="num">{formatRupees(totals?.total ?? 0)}</strong>
            </p>
            <div className="payment" role="radiogroup" aria-label="Payment">
              {PAYMENT_MODES.map(({ mode, label }) => (
                <button
                  key={mode}
                  role="radio"
                  aria-checked={payment === mode}
                  onClick={() => {
                    setPayment(mode);
                    if (mode === 'split') setSheet('split');
                    if (mode === 'credit') setSheet('credit');
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            {paymentNote && (
              <p className="payment-note num" role="status">
                {paymentNote}
              </p>
            )}
            {splitBad && split && <p className="error">The split no longer fits the bill: tap Split again.</p>}
            {canCollectOnline && (
              <label className="check online-toggle">
                <input type="checkbox" checked={online} onChange={(e) => setOnline(e.target.checked)} />
                Collect through Razorpay (needs internet)
              </label>
            )}
            {error && <p className="error" role="alert">{error}</p>}
            <button
              className="primary save"
              onClick={() => void save()}
              disabled={saving || cart.length === 0 || !totals || splitBad || creditBad}
            >
              {saving ? 'Saving…' : canCollectOnline && online ? 'Save and collect' : 'Save and print'}
            </button>
          </div>
        </div>
      </aside>

      {saved && <Receipt bill={saved} onClose={() => setSaved(null)} autoPrint />}
      {sheet === 'discount' && totals && (
        <DiscountSheet
          targets={[
            { key: 'bill', label: 'Whole bill', grossPaise: grossPaise - cart.reduce((a, l) => a + (l.discountPaise ?? 0), 0) },
            ...cart.map((l, i) => ({
              key: l.key,
              label: itemsById.get(l.menuItemId)?.name ?? 'Item',
              grossPaise: totals.lines[i]?.gross ?? 0,
            })),
          ]}
          current={{ bill: billDiscount, ...lineDiscounts }}
          reason={discountReason}
          billGrossPaise={grossPaise}
          otherDiscountPaise={(key) => discountTotal - (key === 'bill' ? billDiscount : lineDiscounts[key] ?? 0)}
          maxBp={catalogue.shop.max_discount_bp ?? 1000}
          isOwner={user?.role === 'owner'}
          onClose={() => setSheet(null)}
          onApply={(key, paise, why) => {
            if (key === 'bill') setBillDiscount(paise);
            else setCart((c) => c.map((l) => (l.key === key ? { ...l, discountPaise: paise } : l)));
            if (paise) setDiscountReason(why);
            setSheet(null);
          }}
        />
      )}
      {sheet === 'split' && totals && (
        <SplitSheet
          totalPaise={totals.total}
          initial={split}
          onClose={() => setSheet(null)}
          onApply={(s) => {
            setSplit(s);
            setSheet(null);
          }}
        />
      )}
      {(sheet === 'customer' || sheet === 'credit') && (
        <CustomerSheet
          initial={customer}
          credit={sheet === 'credit' ? { paidNowPaise: paidNow } : null}
          totalPaise={totals?.total ?? 0}
          onClose={() => setSheet(null)}
          onApply={(c, now) => {
            setCustomer(c);
            if (sheet === 'credit') setPaidNow(now);
            setSheet(null);
          }}
        />
      )}
      {collect && (
        <OnlinePayment
          bill={collect.bill}
          method={collect.method}
          onDone={() => {
            setSaved(collect.bill); // the receipt, printed as for any bill
            setCollect(null);
          }}
        />
      )}
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

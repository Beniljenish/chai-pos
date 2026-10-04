/**
 * Table service (README, "Table service"): the floor, and one order at a time.
 *
 *   floor  -> tap a table -> add items -> Send KOT (kitchen ticket) -> back to the floor
 *          -> later: more rounds, Print bill (the bill brought to the table)
 *          -> Settle (payment mode) -> the tax invoice, made like a counter bill
 *
 * Every action is an order event written on this tablet first (lib/orders.ts), so
 * a waiter keeps working through a network drop. The floor refreshes every few
 * seconds while it is on screen, so what another tablet did shows up quickly.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { saveBill, type CartLine, type PaymentMode } from '../lib/billing';
import { db, type LocalBill } from '../lib/db';
import { billSummaryRows, kotRows, type Row } from '../lib/escpos';
import { formatRupees, GstError } from '../lib/gst';
import { formatPriceDelta } from '../lib/options';
import { act, liveOrders, minutesOpen, nextKotNo, openOrder, sendKot, type LiveOrder, type OpenInput, type OrderLine } from '../lib/orders';
import { loadPrinter } from '../lib/printer';
import { shiftsOn } from '../lib/shift';
import { CANCEL_REASONS, floorModel, kitchenTickets, kotLinesFromCart, orderLabel, priceOrder, type FloorTable } from '../lib/table';
import type { Catalogue } from '../lib/types';
import { KitchenView } from './KitchenView';
import { Receipt } from './Receipt';
import { StartShiftSheet } from './ShiftUI';
import { Sheet } from './Sheet';
import { TicketPreview } from './TicketPreview';
import { useSession } from './session';

const POLL_MS = 5_000;

/** Live orders on this tablet, refreshed after every sync and polled while on screen. */
function useLiveOrders() {
  const { sync, worker } = useSession();
  const [orders, setOrders] = useState<LiveOrder[] | null>(null);
  const reload = useCallback(async () => setOrders(await liveOrders(db)), []);
  useEffect(() => {
    void reload();
  }, [reload, sync?.lastSyncedAt, sync?.pending]);
  useEffect(() => {
    const t = setInterval(() => {
      if (document.visibilityState === 'visible') void worker?.kick();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [worker]);
  return { orders, reload };
}

/** Re-render every 30 s so "12 min" on the floor keeps up. */
function useNow() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  return now;
}

interface Target {
  /** null: a new order, made when its first KOT is sent (an empty table stays free). */
  orderId: string | null;
  start: OpenInput;
}

export function TablesScreen() {
  const { catalogue } = useSession();
  const { orders, reload } = useLiveOrders();
  const [target, setTarget] = useState<Target | null>(null);
  const [newKind, setNewKind] = useState<'takeaway' | 'delivery' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const now = useNow();
  // A tablet in the kitchen stays on the kitchen view, also after a reload.
  const [view, setViewState] = useState<'floor' | 'kitchen'>('floor');
  useEffect(() => {
    void db.getMeta<'floor' | 'kitchen'>('tablesView').then((v) => v && setViewState(v));
  }, []);
  const setView = (v: 'floor' | 'kitchen') => {
    setViewState(v);
    void db.setMeta('tablesView', v);
  };

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice]);

  if (!catalogue) return null;

  if (target) {
    return (
      <OrderScreen
        catalogue={catalogue}
        target={target}
        orders={orders ?? []}
        reload={reload}
        onBack={(message) => {
          setTarget(null);
          setNotice(message ?? null);
          void reload();
        }}
      />
    );
  }

  const floor = floorModel(catalogue, orders ?? [], now);

  function openTable(t: FloorTable) {
    setTarget(
      t.orders.length
        ? { orderId: t.orders[0].id, start: { orderType: 'dine_in', tableId: t.id } }
        : { orderId: null, start: { orderType: 'dine_in', tableId: t.id } },
    );
  }

  const toMake = kitchenTickets(catalogue, orders ?? [], now).length;

  return (
    <main className="floor" aria-busy={orders === null}>
      <header className="floor-head">
        <h1>Tables</h1>
        {view === 'floor' && (
          <div className="floor-actions">
            <button onClick={() => setNewKind('takeaway')}>+ Takeaway</button>
            <button onClick={() => setNewKind('delivery')}>+ Delivery</button>
          </div>
        )}
      </header>
      <div className="view-switch" role="group" aria-label="View">
        <button aria-pressed={view === 'floor'} onClick={() => setView('floor')}>
          Floor
        </button>
        <button aria-pressed={view === 'kitchen'} onClick={() => setView('kitchen')}>
          Kitchen{toMake ? ` (${toMake})` : ''}
        </button>
      </div>
      {notice && (
        <p className="floor-notice" role="status">
          {notice}
        </p>
      )}
      {view === 'kitchen' ? (
        <KitchenView catalogue={catalogue} orders={orders ?? []} now={now} reload={reload} />
      ) : (
        <>
          <p className="floor-legend" aria-hidden="true">
            <span className="dot free" /> Free <span className="dot running" /> Eating <span className="dot billed" /> Bill printed
          </p>

          {floor.areas.map((a) => (
            <section key={a.id} className="floor-area" aria-label={a.name}>
              {floor.areas.length > 1 && <h2>{a.name}</h2>}
              <ul className="floor-grid">
                {a.tables.map((t) => (
                  <li key={t.id}>
                    <button
                      className={`table-tile ${t.status}`}
                      onClick={() => openTable(t)}
                      aria-label={
                        t.status === 'free'
                          ? `Table ${t.name}, free`
                          : `Table ${t.name}, ${t.status === 'billed' ? 'bill printed' : 'eating'}, ${formatRupees(t.totalPaise)}, ${t.minutes} minutes`
                      }
                    >
                      <strong className="table-name">{t.name}</strong>
                      {t.status === 'free' ? (
                        <span className="table-sub">{t.seats} seats</span>
                      ) : (
                        <>
                          <span className="table-amount num">{formatRupees(t.totalPaise)}</span>
                          <span className="table-sub">
                            {t.minutes} min{t.covers ? ` · ${t.covers} guests` : ''}
                          </span>
                        </>
                      )}
                      {t.orders.length > 1 && (
                        <span className="tile-count" title="Two orders on this table">
                          {t.orders.length}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}

          <section className="floor-area" aria-label="Takeaway and delivery">
            <h2>Takeaway and delivery</h2>
            {floor.other.length === 0 ? (
              <p className="muted">None running.</p>
            ) : (
              <ul className="order-list">
                {floor.other.map((o) => {
                  let total = 0;
                  try {
                    total = priceOrder(o.state, catalogue).totals?.total ?? 0;
                  } catch {
                    /* shown on the order screen */
                  }
                  return (
                    <li key={o.id}>
                      <button
                        className={o.state.status}
                        onClick={() => setTarget({ orderId: o.id, start: { orderType: o.state.order_type } })}
                      >
                        <strong>{orderLabel(catalogue, o.state)}</strong>
                        <span className="muted">
                          {minutesOpen(o.state, now)} min{o.state.status === 'billed' ? ' · bill printed' : ''}
                        </span>
                        <span className="num">{formatRupees(total)}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </>
      )}

      {newKind && (
        <NewOrderSheet
          kind={newKind}
          onClose={() => setNewKind(null)}
          onStart={(start) => {
            setNewKind(null);
            setTarget({ orderId: null, start });
          }}
        />
      )}
    </main>
  );
}

function NewOrderSheet({ kind, onClose, onStart }: { kind: 'takeaway' | 'delivery'; onClose(): void; onStart(s: OpenInput): void }) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [messageOk, setMessageOk] = useState(false);
  const [note, setNote] = useState('');
  const phoneOk = phone === '' || /^\d{10}$/.test(phone);
  const ready = phoneOk && (kind === 'takeaway' || phone !== '');
  return (
    <Sheet title={kind === 'takeaway' ? 'New takeaway' : 'New delivery'} onClose={onClose}>
      <label>
        Customer name {kind === 'takeaway' && <span className="muted">(optional)</span>}
        <input value={name} maxLength={80} autoFocus onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Phone {kind === 'takeaway' && <span className="muted">(optional)</span>}
        <input inputMode="numeric" value={phone} maxLength={10} onChange={(e) => {
            setPhone(e.target.value.replace(/\D/g, ''));
            setMessageOk(false); // consent is for one number
          }} />
      </label>
      {!phoneOk && <p className="error">A phone number has 10 digits.</p>}
      <ConsentCheck phone={phone} checked={messageOk} onChange={setMessageOk} />
      {kind === 'delivery' && (
        <label>
          Address or note
          <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
        </label>
      )}
      <div className="sheet-actions">
        <button
          className="primary"
          disabled={!ready}
          onClick={() =>
            onStart({ orderType: kind, customerName: name.trim(), customerPhone: phone, messageOk: messageOk && phone !== '', note: note.trim() })
          }
        >
          Start order
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------------------- one order
interface Draft extends CartLine {
  key: string;
  note: string;
}

const PAYMENT_MODES: { mode: PaymentMode; label: string }[] = [
  { mode: 'cash', label: 'Cash' },
  { mode: 'upi', label: 'UPI' },
  { mode: 'card', label: 'Card' },
];

type Overlay =
  | { kind: 'ticket'; title: string; rows: Row[]; autoPrint: boolean; then?: string }
  | { kind: 'cancel-line'; line: OrderLine }
  | { kind: 'cancel-order' }
  | { kind: 'move' }
  | { kind: 'details' }
  | { kind: 'settle' }
  | { kind: 'shift' }
  | { kind: 'receipt'; bill: LocalBill };

function OrderScreen({
  catalogue,
  target,
  orders,
  reload,
  onBack,
}: {
  catalogue: Catalogue;
  target: Target;
  orders: LiveOrder[];
  reload(): Promise<void>;
  onBack(message?: string): void;
}) {
  const { device, user, worker, shift } = useSession();
  const [orderId, setOrderId] = useState(target.orderId);
  const [start, setStart] = useState(target.start);
  const [draft, setDraft] = useState<Draft[]>([]);
  const [noteFor, setNoteFor] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tillOpen, setTillOpen] = useState(false);
  const [payment, setPayment] = useState<PaymentMode>('cash');

  const live = orderId ? orders.find((o) => o.id === orderId) : undefined;
  const state = live?.state;
  const items = useMemo(() => catalogue.menu_items.filter((m) => m.is_active), [catalogue]);
  const categories = useMemo(() => [...new Set(items.map((i) => i.category))], [items]);
  const activeCategory = category ?? categories[0] ?? null;
  const modifiers = useMemo(() => new Map(catalogue.modifiers.map((m) => [m.id, m])), [catalogue]);
  const itemsById = useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);

  const priced = useMemo(() => {
    if (!state) return null;
    try {
      return priceOrder(state, catalogue);
    } catch {
      return null;
    }
  }, [state, catalogue]);
  // priceOrder() returns the lines still charged, in order: pair them back up by id.
  const lineTotals = useMemo(
    () => new Map(state ? activeLines(state).map((l, i) => [l.line_id, priced?.lines[i]?.totals.total ?? 0]) : []),
    [state, priced],
  );
  const draftTotal = useMemo(() => {
    try {
      return draft.length
        ? (priceOrder({ ...(state ?? emptyFor(start)), lines: kotLinesFromCart(draft, catalogue).map(asLine) }, catalogue).totals?.total ??
            0)
        : 0;
    } catch {
      return 0;
    }
  }, [draft, catalogue, state, start]);

  // The order was finished on another tablet while this one had it open.
  if (orderId && !live && !overlay && !busy) {
    return (
      <main className="centered">
        <div className="panel">
          <h1>This order is closed</h1>
          <p>It was settled or cancelled on another tablet.</p>
          <button className="primary" onClick={() => onBack()}>
            Back to tables
          </button>
        </div>
      </main>
    );
  }

  const label = state ? orderLabel(catalogue, state) : orderLabel(catalogue, emptyFor(start));
  const by = user?.id ?? '';
  const byName = user?.name ?? '';
  const covers = state?.covers ?? start.covers ?? 0;
  const billed = state?.status === 'billed';
  const sentCount = state?.lines.reduce((n, l) => n + l.qty, 0) ?? 0;
  const draftCount = draft.reduce((n, l) => n + l.qty, 0);
  const total = priced?.totals?.total ?? 0;

  function add(menuItemId: string) {
    setDraft((d) => {
      const same = d.find((l) => l.menuItemId === menuItemId && l.modifierIds.length === 0 && !l.note);
      if (same) return d.map((l) => (l === same ? { ...l, qty: l.qty + 1 } : l));
      return [...d, { key: crypto.randomUUID(), menuItemId, qty: 1, modifierIds: [], note: '' }];
    });
  }
  const setQty = (key: string, qty: number) =>
    setDraft((d) => (qty <= 0 ? d.filter((l) => l.key !== key) : d.map((l) => (l.key === key ? { ...l, qty } : l))));
  const toggleModifier = (key: string, id: string) =>
    setDraft((d) =>
      d.map((l) =>
        l.key !== key
          ? l
          : { ...l, modifierIds: l.modifierIds.includes(id) ? l.modifierIds.filter((m) => m !== id) : [...l.modifierIds, id] },
      ),
    );
  const setNote = (key: string, note: string) => setDraft((d) => d.map((l) => (l.key === key ? { ...l, note } : l)));

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof GstError || e instanceof Error ? e.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  const sendRound = () =>
    run(async () => {
      if (!device || draft.length === 0) return;
      const lines = kotLinesFromCart(draft, catalogue);
      let id = orderId;
      if (!id) {
        id = await openOrder(db, start, by);
        setOrderId(id);
      }
      const kotNo = await nextKotNo(db, device.id, device.code);
      await sendKot(db, id, kotNo, lines, by);
      setDraft([]);
      await reload();
      void worker?.kick();
      const printer = await loadPrinter(db);
      if (!printer.printKot) return onBack(`KOT ${kotNo} sent for ${label}`);
      setOverlay({
        kind: 'ticket',
        title: `KOT ${kotNo}`,
        autoPrint: true,
        then: `KOT ${kotNo} sent for ${label}`,
        rows: kotRows({ kind: 'KOT', kotNo, label, at: new Date().toISOString(), byName, covers, lines }, printer.width),
      });
    });

  const printBill = () =>
    run(async () => {
      if (!orderId || !state || !priced?.totals) return;
      await act(db, orderId, 'bill_printed', {}, by);
      await reload();
      void worker?.kick();
      const printer = await loadPrinter(db);
      setOverlay({
        kind: 'ticket',
        title: `Bill for ${label}`,
        autoPrint: printer.autoPrint,
        then: `Bill printed for ${label}`,
        rows: billSummaryRows(
          {
            label,
            covers,
            at: new Date().toISOString(),
            copy: state.bill_prints + 1,
            gstType: catalogue.shop.gst_type,
            lines: priced.lines,
            totals: priced.totals,
          },
          catalogue.shop,
          printer.width,
        ),
      });
    });

  async function settle(shiftId = shift?.id) {
    if (!device || !orderId || !priced?.totals) return;
    const needShift = shiftsOn(catalogue.shop.cash_shifts);
    if (needShift && !shiftId) return setOverlay({ kind: 'shift' });
    await run(async () => {
      // The invoice first (it is the money); then the order is marked settled with it.
      const bill = await saveBill({
        db,
        deviceId: device.id,
        deviceCode: device.code,
        catalogue,
        cart: [],
        lines: priced.lines,
        orderId,
        paymentMode: payment,
        cashierId: user?.id,
        shiftId: needShift ? shiftId : undefined,
      });
      await act(db, orderId, 'settle', { bill_id: bill.id }, by);
      void worker?.kick();
      setOverlay({ kind: 'receipt', bill });
    });
  }

  return (
    <div className="billing order-screen">
      <section className="menu" aria-label="Menu">
        <header className="order-head">
          <button className="quiet back" onClick={() => onBack()} aria-label="Back to tables">
            ← Tables
          </button>
          <div className="order-title">
            <h1>{label}</h1>
            <span className="muted">
              {state ? `${minutesOpen(state)} min` : 'New order'}
              {covers ? ` · ${covers} guests` : ''}
              {state?.kots.length ? ` · ${state.kots.length} KOT${state.kots.length > 1 ? 's' : ''}` : ''}
            </span>
          </div>
          <button onClick={() => setOverlay({ kind: 'details' })}>{start.orderType === 'dine_in' ? 'Guests' : 'Customer'}</button>
        </header>
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
              const inDraft = draft.filter((l) => l.menuItemId === i.id).reduce((n, l) => n + l.qty, 0);
              return (
                <button key={i.id} className="tile" onClick={() => add(i.id)}>
                  <span className="tile-name">{i.name}</span>
                  <span className="tile-price">{formatRupees(i.price_paise)}</span>
                  {inDraft > 0 && (
                    <span className="tile-count" aria-label={`${inDraft} in this round`}>
                      {inDraft}
                    </span>
                  )}
                </button>
              );
            })}
        </div>
      </section>

      <aside className={`till ${tillOpen ? 'open' : ''}`} aria-label="Order">
        <button className="till-handle" onClick={() => setTillOpen((o) => !o)} aria-expanded={tillOpen}>
          <span>
            {draftCount
              ? `${draftCount} new, not sent`
              : sentCount
                ? `${label}: ${sentCount} item${sentCount > 1 ? 's' : ''}`
                : 'Nothing ordered'}
          </span>
          <strong className="num">{formatRupees(total + draftTotal)}</strong>
        </button>

        <div className="till-body">
          <div className="order-scroll">
            {draft.length > 0 && (
              <>
                <h2 className="till-title">New round</h2>
                {billed && <p className="till-warn">The bill was printed. Adding items reopens it; print it again before settling.</p>}
                <ul className="lines">
                  {draft.map((l) => {
                    const item = itemsById.get(l.menuItemId);
                    if (!item) return null;
                    return (
                      <li key={l.key}>
                        <div className="line-top">
                          <span className="line-name">{item.name}</span>
                        </div>
                        <div className="line-controls">
                          <div className="stepper">
                            <button onClick={() => setQty(l.key, l.qty - 1)} aria-label={`One less ${item.name}`}>
                              −
                            </button>
                            <span className="num" aria-live="polite">
                              {l.qty}
                            </span>
                            <button onClick={() => setQty(l.key, l.qty + 1)} aria-label={`One more ${item.name}`}>
                              +
                            </button>
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
                          <button
                            className="chip"
                            aria-pressed={Boolean(l.note) || noteFor === l.key}
                            onClick={() => setNoteFor(noteFor === l.key ? null : l.key)}
                          >
                            Note
                          </button>
                        </div>
                        {(noteFor === l.key || l.note) && (
                          <input
                            className="line-note"
                            aria-label={`Note for the kitchen: ${item.name}`}
                            placeholder="Less sugar, no ice…"
                            maxLength={200}
                            value={l.note}
                            onChange={(e) => setNote(l.key, e.target.value)}
                          />
                        )}
                      </li>
                    );
                  })}
                </ul>
                <button className="primary save kot" disabled={busy} onClick={() => void sendRound()}>
                  {busy ? 'Sending…' : `Send to kitchen (${draftCount})`}
                </button>
              </>
            )}

            {state && state.lines.length > 0 && (
              <>
                <h2 className="till-title">Ordered</h2>
                <ul className="lines ordered">
                  {state.lines.map((l) => {
                    const lineTotal = lineTotals.get(l.line_id);
                    return (
                      <li key={l.line_id} className={l.qty === 0 ? 'gone' : ''}>
                        <div className="line-top">
                          <span className="line-name">
                            {l.qty > 0 ? `${l.qty} × ` : ''}
                            {l.name}
                            {l.modifiers.length ? ` (${l.modifiers.map((m) => m.name).join(', ')})` : ''}
                          </span>
                          <span className="num">{l.qty > 0 && lineTotal !== undefined ? formatRupees(lineTotal) : ''}</span>
                        </div>
                        <div className="line-meta">
                          <span>
                            KOT {l.kot_no}
                            {l.cancelled_qty ? ` · ${l.cancelled_qty} cancelled` : ''}
                            {l.ready && l.qty > 0 ? ' · Ready' : ''}
                            {l.note ? ` · ${l.note}` : ''}
                          </span>
                          {l.qty > 0 && (
                            <button
                              className="quiet"
                              onClick={() => setOverlay({ kind: 'cancel-line', line: l })}
                              aria-label={`Cancel ${l.name}`}
                            >
                              Cancel
                            </button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}

            {!draft.length && !state?.lines.length && <p className="empty">Tap items on the menu to start a round.</p>}
          </div>

          <div className="till-foot">
            {live && live.unsent > 0 && <p className="tax-note">Saved on this tablet; sending…</p>}
            {priced?.totals && catalogue.shop.gst_type === 'regular' && priced.totals.cgst > 0 && (
              <p className="tax-note num">Includes GST {formatRupees(priced.totals.cgst + priced.totals.sgst)}</p>
            )}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            {state && state.lines.length > 0 && (
              <>
                <p className="total">
                  <span>{billed ? 'Bill printed' : draft.length ? 'Sent so far' : 'Total'}</span>
                  <strong className="num">{formatRupees(total)}</strong>
                </p>
                <div className="order-actions">
                  <button disabled={busy || !priced?.totals || draft.length > 0} onClick={() => void printBill()}>
                    {billed ? 'Print bill again' : 'Print bill'}
                  </button>
                  <button
                    className="primary"
                    disabled={busy || !priced?.totals || draft.length > 0}
                    onClick={() => setOverlay({ kind: 'settle' })}
                  >
                    Settle
                  </button>
                </div>
              </>
            )}
            {draft.length > 0 && priced?.totals && <p className="tax-note">Send or clear the new round before the bill.</p>}
            <div className="order-more">
              {start.orderType === 'dine_in' && state && (
                <button className="quiet" onClick={() => setOverlay({ kind: 'move' })}>
                  Move table
                </button>
              )}
              {state && (
                <button className="quiet" onClick={() => setOverlay({ kind: 'cancel-order' })}>
                  Cancel order
                </button>
              )}
              {draft.length > 0 && (
                <button className="quiet" onClick={() => setDraft([])}>
                  Clear new round
                </button>
              )}
            </div>
          </div>
        </div>
      </aside>

      {overlay?.kind === 'ticket' && (
        <TicketPreview
          title={overlay.title}
          rows={overlay.rows}
          autoPrint={overlay.autoPrint}
          onClose={() => {
            setOverlay(null);
            if (overlay.then !== undefined) onBack(overlay.then); // a cancel ticket stays on the order
          }}
        />
      )}
      {overlay?.kind === 'cancel-line' && state && orderId && (
        <CancelLineSheet
          line={overlay.line}
          billed={state.bill_prints > 0}
          onClose={() => setOverlay(null)}
          onConfirm={(qty, reason) =>
            run(async () => {
              await act(db, orderId, 'cancel', { line_id: overlay.line.line_id, qty, reason }, by);
              await reload();
              void worker?.kick();
              const printer = await loadPrinter(db);
              if (!printer.printKot) return setOverlay(null);
              setOverlay({
                kind: 'ticket',
                title: `Cancel ${overlay.line.kot_no}`,
                autoPrint: true,
                rows: kotRows(
                  {
                    kind: 'CANCEL',
                    kotNo: overlay.line.kot_no,
                    label,
                    at: new Date().toISOString(),
                    byName,
                    lines: [{ name: overlay.line.name, qty, modifiers: overlay.line.modifiers }],
                    reason,
                  },
                  printer.width,
                ),
              });
            })
          }
        />
      )}
      {overlay?.kind === 'cancel-order' && state && orderId && (
        <CancelOrderSheet
          hasItems={state.lines.some((l) => l.qty > 0)}
          onClose={() => setOverlay(null)}
          onConfirm={(reason) =>
            run(async () => {
              const left = state.lines.filter((l) => l.qty > 0);
              await act(db, orderId, 'cancel_order', { reason }, by);
              void worker?.kick();
              const printer = await loadPrinter(db);
              if (!left.length || !printer.printKot) return onBack(`${label}: order cancelled`);
              setOverlay({
                kind: 'ticket',
                title: 'Cancel order',
                autoPrint: true,
                then: `${label}: order cancelled`,
                rows: kotRows(
                  {
                    kind: 'CANCEL',
                    kotNo: 'ALL',
                    label,
                    at: new Date().toISOString(),
                    byName,
                    lines: left.map((l) => ({ name: l.name, qty: l.qty, modifiers: l.modifiers })),
                    reason,
                  },
                  printer.width,
                ),
              });
            })
          }
        />
      )}
      {overlay?.kind === 'move' && state && orderId && (
        <MoveSheet
          catalogue={catalogue}
          orders={orders}
          current={state.table_id}
          onClose={() => setOverlay(null)}
          onMove={(tableId, name) =>
            run(async () => {
              await act(db, orderId, 'move', { table_id: tableId }, by);
              void worker?.kick();
              setOverlay(null);
              onBack(`${label} moved to ${name}`);
            })
          }
        />
      )}
      {overlay?.kind === 'details' && (
        <DetailsSheet
          dineIn={start.orderType === 'dine_in'}
          initial={{
            covers,
            customerName: state?.customer_name ?? start.customerName ?? '',
            customerPhone: state?.customer_phone ?? start.customerPhone ?? '',
            messageOk: state?.message_ok ?? start.messageOk ?? false,
            note: state?.note ?? start.note ?? '',
          }}
          onClose={() => setOverlay(null)}
          onSave={(d) =>
            run(async () => {
              if (orderId && state) {
                const changed: Record<string, unknown> = {};
                if (d.covers !== state.covers) changed.covers = d.covers;
                if (d.customerName !== state.customer_name) changed.customer_name = d.customerName;
                if (d.customerPhone !== state.customer_phone) changed.customer_phone = d.customerPhone;
                const ok = d.messageOk && d.customerPhone !== '';
                // Sent with the number whenever the number changes: consent is per number.
                if (ok !== state.message_ok || 'customer_phone' in changed) changed.message_ok = ok;
                if (d.note !== state.note) changed.note = d.note;
                if (Object.keys(changed).length) {
                  await act(db, orderId, 'details', changed, by);
                  await reload();
                  void worker?.kick();
                }
              } else {
                setStart((s) => ({ ...s, ...d }));
              }
              setOverlay(null);
            })
          }
        />
      )}
      {overlay?.kind === 'settle' && priced?.totals && (
        <Sheet title={`Settle ${label}`} onClose={() => setOverlay(null)}>
          <p className="settle-total">
            <span>To pay</span>
            <strong className="num">{formatRupees(priced.totals.total)}</strong>
          </p>
          {!billed && <p className="muted">The bill was not printed; the receipt printed now is the customer&apos;s bill.</p>}
          <div className="payment" role="radiogroup" aria-label="Payment">
            {PAYMENT_MODES.map(({ mode, label: l }) => (
              <button key={mode} role="radio" aria-checked={payment === mode} onClick={() => setPayment(mode)}>
                {l}
              </button>
            ))}
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="sheet-actions">
            <button className="primary save" disabled={busy} onClick={() => void settle()}>
              {busy ? 'Saving…' : 'Settle and print receipt'}
            </button>
          </div>
        </Sheet>
      )}
      {overlay?.kind === 'shift' && (
        <StartShiftSheet
          onClose={() => setOverlay(null)}
          onStarted={(s) => {
            setOverlay(null);
            void settle(s.id);
          }}
        />
      )}
      {overlay?.kind === 'receipt' && (
        <Receipt
          bill={overlay.bill}
          autoPrint
          doneLabel="Back to tables"
          onClose={() => {
            setOverlay(null);
            onBack(`${label} settled: ${overlay.bill.invoiceNo}`);
          }}
        />
      )}
    </div>
  );
}

/** Lines still charged, in the order priceOrder() returns them. */
const activeLines = (s: { lines: OrderLine[] }) => s.lines.filter((l) => l.qty > 0);

/** A not-yet-opened order as a state, for its label and draft pricing. */
function emptyFor(start: OpenInput) {
  return {
    order_type: start.orderType,
    table_id: start.tableId ?? null,
    covers: start.covers ?? 0,
    customer_name: start.customerName ?? '',
    customer_phone: start.customerPhone ?? '',
    message_ok: Boolean(start.messageOk && start.customerPhone),
    note: start.note ?? '',
    status: 'open' as const,
    opened_at: null,
    opened_by: null,
    lines: [],
    kots: [],
    cancellations: [],
    bill_prints: 0,
    changed_after_bill: false,
    bill_id: null,
    settled_at: null,
    cancel_reason: null,
    last_at: null,
  };
}

/** A KOT line as an order line, to price a draft round with the same rules. */
function asLine(l: ReturnType<typeof kotLinesFromCart>[number]): OrderLine {
  return {
    ...l,
    kot_no: '',
    cancelled_qty: 0,
    modifiers: l.modifiers ?? [],
    note: l.note ?? '',
    ready: false,
    added_after_bill: false,
  };
}

// ---------------------------------------------------------------- sheets
function ReasonPicker({ reason, setReason }: { reason: string; setReason(r: string): void }) {
  return (
    <>
      <div className="chips" role="group" aria-label="Reason">
        {CANCEL_REASONS.map((r) => (
          <button key={r} className="chip" aria-pressed={reason === r} onClick={() => setReason(r)}>
            {r}
          </button>
        ))}
      </div>
      <label>
        Reason
        <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} />
      </label>
    </>
  );
}

function CancelLineSheet({
  line,
  billed,
  onClose,
  onConfirm,
}: {
  line: OrderLine;
  billed: boolean;
  onClose(): void;
  onConfirm(qty: number, reason: string): void;
}) {
  const [qty, setQty] = useState(1);
  const [reason, setReason] = useState('');
  return (
    <Sheet title={`Cancel ${line.name}`} onClose={onClose}>
      <p className="muted">
        Sent to the kitchen on KOT {line.kot_no}. The owner sees every cancellation with its reason.
        {billed && ' The bill was already printed: it will need printing again.'}
      </p>
      {line.qty > 1 && (
        <div className="stepper" aria-label="How many to cancel">
          <button onClick={() => setQty((q) => Math.max(1, q - 1))} aria-label="One fewer">
            −
          </button>
          <span className="num">
            {qty} of {line.qty}
          </span>
          <button onClick={() => setQty((q) => Math.min(line.qty, q + 1))} aria-label="One more">
            +
          </button>
        </div>
      )}
      <ReasonPicker reason={reason} setReason={setReason} />
      <div className="sheet-actions">
        <button className="danger" disabled={!reason.trim()} onClick={() => onConfirm(qty, reason.trim())}>
          Cancel {qty} {line.name}
        </button>
        <button onClick={onClose}>Keep it</button>
      </div>
    </Sheet>
  );
}

function CancelOrderSheet({ hasItems, onClose, onConfirm }: { hasItems: boolean; onClose(): void; onConfirm(reason: string): void }) {
  const [reason, setReason] = useState(hasItems ? '' : 'Opened by mistake');
  return (
    <Sheet title="Cancel the whole order" onClose={onClose}>
      <p className="muted">
        {hasItems
          ? 'Nothing is charged and the table is freed. The kitchen gets a cancel ticket; the owner sees the reason.'
          : 'Nothing was ordered. The table is freed.'}
      </p>
      <ReasonPicker reason={reason} setReason={setReason} />
      <div className="sheet-actions">
        <button className="danger" disabled={!reason.trim()} onClick={() => onConfirm(reason.trim())}>
          Cancel order
        </button>
        <button onClick={onClose}>Keep it</button>
      </div>
    </Sheet>
  );
}

function MoveSheet({
  catalogue,
  orders,
  current,
  onClose,
  onMove,
}: {
  catalogue: Catalogue;
  orders: LiveOrder[];
  current: string | null;
  onClose(): void;
  onMove(tableId: string, name: string): void;
}) {
  const floor = floorModel(catalogue, orders);
  return (
    <Sheet title="Move to table" onClose={onClose}>
      <p className="muted">Free tables only. The kitchen tickets already sent stay as they are.</p>
      {floor.areas.map((a) => (
        <div key={a.id}>
          {floor.areas.length > 1 && <h3>{a.name}</h3>}
          <div className="chips">
            {a.tables
              .filter((t) => t.status === 'free' && t.id !== current)
              .map((t) => (
                <button key={t.id} className="chip" onClick={() => onMove(t.id, t.name)}>
                  {t.name}
                </button>
              ))}
          </div>
        </div>
      ))}
    </Sheet>
  );
}

interface Details {
  covers: number;
  customerName: string;
  customerPhone: string;
  messageOk: boolean;
  note: string;
}

/**
 * Messages go only to customers who said yes for that number (README, Phase 8b).
 * Shown once a full number is typed; off by default.
 */
function ConsentCheck({ phone, checked, onChange }: { phone: string; checked: boolean; onChange(v: boolean): void }) {
  if (!/^\d{10}$/.test(phone)) return null;
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      Customer agrees to get the receipt and &quot;order ready&quot; on this number by iMessage
    </label>
  );
}

function DetailsSheet({
  dineIn,
  initial,
  onClose,
  onSave,
}: {
  dineIn: boolean;
  initial: Details;
  onClose(): void;
  onSave(d: Details): void;
}) {
  const [d, setD] = useState(initial);
  const phoneOk = d.customerPhone === '' || /^\d{10}$/.test(d.customerPhone);
  return (
    <Sheet title={dineIn ? 'Guests and customer' : 'Customer'} onClose={onClose}>
      {dineIn && (
        <>
          <p className="field-label">Guests</p>
          <div className="chips" role="group" aria-label="Guests">
            {[1, 2, 3, 4, 5, 6, 8, 10].map((n) => (
              <button key={n} className="chip" aria-pressed={d.covers === n} onClick={() => setD({ ...d, covers: n })}>
                {n}
              </button>
            ))}
          </div>
        </>
      )}
      <label>
        Customer name
        <input value={d.customerName} maxLength={80} onChange={(e) => setD({ ...d, customerName: e.target.value })} />
      </label>
      <label>
        Phone
        <input
          inputMode="numeric"
          value={d.customerPhone}
          maxLength={10}
          onChange={(e) => setD({ ...d, customerPhone: e.target.value.replace(/\D/g, ''), messageOk: false })}
        />
      </label>
      {!phoneOk && <p className="error">A phone number has 10 digits.</p>}
      <ConsentCheck phone={d.customerPhone} checked={d.messageOk} onChange={(v) => setD({ ...d, messageOk: v })} />
      <label>
        Note
        <input value={d.note} maxLength={200} onChange={(e) => setD({ ...d, note: e.target.value })} />
      </label>
      <div className="sheet-actions">
        <button
          className="primary"
          disabled={!phoneOk}
          onClick={() => onSave({ ...d, customerName: d.customerName.trim(), note: d.note.trim() })}
        >
          Save
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </Sheet>
  );
}

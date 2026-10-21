/**
 * What a customer sees after scanning a food court's QR: pick an outlet, pick
 * dishes, give a name and phone, then follow the order by its token. No login,
 * no staff app, nothing stored but their own name and the order they placed.
 * Payment is at the counter (README, "9.11").
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  byCategory,
  cartCount,
  cartTotal,
  changeQty,
  cleanPhone,
  orderProblem,
  soldOutInCart,
  STATUS_TEXT,
  statusStep,
  type Cart,
} from '../lib/foodcourt';
import { formatRupees } from '../lib/gst';
import { PublicError, publicApi, type PublicCourt, type PublicMenu, type PublicOrder } from '../lib/publicApi';

// ---- what the phone remembers (every read and write may fail: private windows)
const mine = 'taptallow-customer';
const orderKey = (slug: string) => `taptallow-order:${slug}`;
function remembered(): { name: string; phone: string } {
  try {
    return { name: '', phone: '', ...JSON.parse(localStorage.getItem(mine) ?? '{}') };
  } catch {
    return { name: '', phone: '' };
  }
}
function remember(name: string, phone: string) {
  try {
    localStorage.setItem(mine, JSON.stringify({ name, phone }));
  } catch {
    /* fine: they type it again next time */
  }
}
function savedOrder(slug: string): string | null {
  try {
    return localStorage.getItem(orderKey(slug));
  } catch {
    return null;
  }
}
function saveOrder(slug: string, key: string | null) {
  try {
    if (key) localStorage.setItem(orderKey(slug), key);
    else localStorage.removeItem(orderKey(slug));
  } catch {
    /* fine */
  }
}

type View =
  | { kind: 'court' }
  | { kind: 'menu'; outletId: string }
  | { kind: 'checkout'; outletId: string; menu: PublicMenu; cart: Cart }
  | { kind: 'status'; key: string };

export function CustomerApp({ slug }: { slug: string }) {
  const [court, setCourt] = useState<PublicCourt | null>(null);
  const [missing, setMissing] = useState(false);
  const [view, setView] = useState<View>(() => {
    const key = savedOrder(slug);
    return key ? { kind: 'status', key } : { kind: 'court' };
  });
  // The cart survives going back to the menu from checkout.
  const [carts, setCarts] = useState<Record<string, Cart>>({});

  useEffect(() => {
    publicApi
      .court(slug)
      .then((c) => {
        setCourt(c);
        document.title = c.name;
      })
      .catch((e) => setMissing(e instanceof PublicError && e.status === 404));
  }, [slug]);

  if (missing) {
    return (
      <main className="cx">
        <h1>We could not find this food court</h1>
        <p className="muted">Please scan the QR code again, or ask at the counter.</p>
      </main>
    );
  }

  return (
    <main className="cx">
      {view.kind === 'status' ? (
        <StatusScreen
          orderKey={view.key}
          onAgain={() => {
            saveOrder(slug, null);
            setView({ kind: 'court' });
          }}
        />
      ) : view.kind === 'checkout' ? (
        <Checkout
          slug={slug}
          outletId={view.outletId}
          menu={view.menu}
          cart={view.cart}
          onBack={() => setView({ kind: 'menu', outletId: view.outletId })}
          onPlaced={(key) => {
            saveOrder(slug, key);
            setCarts((c) => ({ ...c, [view.outletId]: {} }));
            setView({ kind: 'status', key });
          }}
        />
      ) : view.kind === 'menu' ? (
        <Menu
          slug={slug}
          outletId={view.outletId}
          cart={carts[view.outletId] ?? {}}
          setCart={(cart) => setCarts((c) => ({ ...c, [view.outletId]: cart }))}
          onBack={() => setView({ kind: 'court' })}
          onCheckout={(menu) => setView({ kind: 'checkout', outletId: view.outletId, menu, cart: carts[view.outletId] ?? {} })}
        />
      ) : (
        <CourtScreen court={court} onPick={(outletId) => setView({ kind: 'menu', outletId })} />
      )}
    </main>
  );
}

// ---------------------------------------------------------------- outlets
function CourtScreen({ court, onPick }: { court: PublicCourt | null; onPick(outletId: string): void }) {
  return (
    <>
      <header className="cx-hero">
        <small>Welcome to</small>
        <h1>{court?.name ?? ' '}</h1>
        <p>Pick an outlet to order from</p>
      </header>
      {court === null ? (
        <p className="muted" role="status">
          Loading…
        </p>
      ) : (
        <ul className="cx-list" aria-label="Outlets">
          {court.outlets.map((o) => (
            <li key={o.id}>
              <button className="cx-outlet" onClick={() => onPick(o.id)}>
                <span className="cx-logo" aria-hidden="true">
                  {o.name
                    .split(/\s+/)
                    .map((w) => w[0])
                    .join('')
                    .slice(0, 2)
                    .toUpperCase()}
                </span>
                <strong>{o.name}</strong>
                <span className={`cx-tag ${o.open ? 'open' : 'shut'}`}>{o.open ? 'Open' : 'Closed'}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ---------------------------------------------------------------- one outlet's menu
function Menu({
  slug,
  outletId,
  cart,
  setCart,
  onBack,
  onCheckout,
}: {
  slug: string;
  outletId: string;
  cart: Cart;
  setCart(c: Cart): void;
  onBack(): void;
  onCheckout(menu: PublicMenu): void;
}) {
  const [menu, setMenu] = useState<PublicMenu | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    publicApi
      .menu(slug, outletId)
      .then((m) => {
        setMenu(m);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, [slug, outletId]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 60_000); // dishes sell out while people browse
    return () => window.clearInterval(timer);
  }, [load]);

  const total = menu ? cartTotal(menu.items, cart, menu.gst_type) : 0;
  const count = cartCount(cart);
  const gone = menu ? soldOutInCart(menu.items, cart) : [];

  return (
    <>
      <header className="cx-top">
        <button className="cx-back" onClick={onBack} aria-label="Back to outlets">
          ‹
        </button>
        <h1>{menu?.outlet ?? ' '}</h1>
      </header>
      {failed && !menu && (
        <p className="error" role="alert">
          Could not load the menu. <button onClick={load}>Try again</button>
        </p>
      )}
      {menu && !menu.open && <p className="cx-note">This outlet is not taking orders right now.</p>}
      {menu &&
        byCategory(menu.items).map((g) => (
          <section key={g.category} aria-label={g.category}>
            <h2>{g.category}</h2>
            <ul className="cx-list">
              {g.items.map((i) => {
                const qty = cart[i.id] ?? 0;
                return (
                  <li key={i.id} className={`cx-dish ${i.sold_out ? 'gone' : ''}`}>
                    <div>
                      <strong>{i.name}</strong>
                      {i.sold_out && <span className="muted"> Sold out today</span>}
                    </div>
                    <span className="num">{formatRupees(i.price_paise)}</span>
                    {i.sold_out || !menu.open ? null : qty === 0 ? (
                      <button className="cx-add" aria-label={`Add ${i.name}`} onClick={() => setCart(changeQty(cart, i.id, 1))}>
                        +
                      </button>
                    ) : (
                      <span className="cx-step">
                        <button aria-label={`Remove one ${i.name}`} onClick={() => setCart(changeQty(cart, i.id, -1))}>
                          −
                        </button>
                        <span aria-label={`${qty} ${i.name}`}>{qty}</span>
                        <button aria-label={`Add one more ${i.name}`} onClick={() => setCart(changeQty(cart, i.id, 1))}>
                          +
                        </button>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      {gone.length > 0 && (
        <p className="error" role="alert">
          Sold out since you picked it: {gone.join(', ')}. Remove it to continue.
        </p>
      )}
      {count > 0 && menu && (
        <div className="cx-bar">
          <span>
            {count} item{count === 1 ? '' : 's'} · {formatRupees(total)}
          </span>
          <button className="primary" disabled={gone.length > 0 || !menu.open} onClick={() => onCheckout(menu)}>
            View order
          </button>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------- name, phone, place
function Checkout({
  slug,
  outletId,
  menu,
  cart,
  onBack,
  onPlaced,
}: {
  slug: string;
  outletId: string;
  menu: PublicMenu;
  cart: Cart;
  onBack(): void;
  onPlaced(statusKey: string): void;
}) {
  const saved = useMemo(() => remembered(), []);
  const [name, setName] = useState(saved.name);
  const [phone, setPhone] = useState(saved.phone);
  const [note, setNote] = useState('');
  const [consent, setConsent] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // One id for this order: tapping twice, or retrying after a bad signal, is one order.
  const requestId = useMemo(() => crypto.randomUUID(), []);

  const items = menu.items.filter((i) => (cart[i.id] ?? 0) > 0);
  const total = cartTotal(menu.items, cart, menu.gst_type);
  const clean = cleanPhone(phone);
  const ready = name.trim() !== '' && clean !== null && items.length > 0;

  async function place() {
    if (!ready || clean === null) return;
    setBusy(true);
    setError(null);
    try {
      const placed = await publicApi.place(slug, outletId, {
        request_id: requestId,
        name: name.trim(),
        phone: clean,
        note: note.trim(),
        message_ok: consent,
        items: items.map((i) => ({ menu_item_id: i.id, qty: cart[i.id] })),
      });
      remember(name.trim(), clean);
      onPlaced(placed.status_key);
    } catch (e) {
      setError(e instanceof PublicError ? orderProblem(e.code, e.names) : 'No signal. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="cx-top">
        <button className="cx-back" onClick={onBack} aria-label="Back to the menu">
          ‹
        </button>
        <h1>Your order · {menu.outlet}</h1>
      </header>
      <ul className="cx-summary" aria-label="Your order">
        {items.map((i) => (
          <li key={i.id}>
            <span>
              {cart[i.id]} × {i.name}
            </span>
          </li>
        ))}
        <li className="cx-total">
          <strong>Total</strong>
          <strong className="num">{formatRupees(total)}</strong>
        </li>
      </ul>
      <form
        className="cx-form"
        onSubmit={(e) => {
          e.preventDefault();
          void place();
        }}
      >
        <label>
          Your name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="name" required />
        </label>
        <label>
          Mobile number
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            inputMode="tel"
            autoComplete="tel"
            aria-invalid={phone !== '' && clean === null}
            required
          />
        </label>
        {phone !== '' && clean === null && <p className="error">A mobile number has 10 digits.</p>}
        <label>
          Note for the outlet <span className="muted">(optional)</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={120} />
        </label>
        <label className="cx-check">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          Message me on this number when my order is ready
        </label>
        <p className="cx-note">
          You pay <strong>{formatRupees(total)} at the counter</strong> when you collect.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={!ready || busy}>
          {busy ? 'Placing…' : 'Place order'}
        </button>
      </form>
    </>
  );
}

// ---------------------------------------------------------------- the token page
function StatusScreen({ orderKey: key, onAgain }: { orderKey: string; onAgain(): void }) {
  const [order, setOrder] = useState<PublicOrder | null>(null);
  const [lost, setLost] = useState(false);

  const done = order?.status === 'collected' || order?.status === 'declined';

  useEffect(() => {
    let live = true;
    const poll = () =>
      publicApi
        .order(key)
        .then((o) => live && (setOrder(o), setLost(false)))
        .catch((e) => live && e instanceof PublicError && e.status === 404 && setLost(true));
    void poll();
    if (done) return () => void (live = false);
    const timer = window.setInterval(poll, 5000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [key, done]);

  if (lost) {
    return (
      <>
        <h1>We could not find this order</h1>
        <button className="primary" onClick={onAgain}>
          Back to the food court
        </button>
      </>
    );
  }
  if (!order) {
    return (
      <p className="muted" role="status">
        Loading your order…
      </p>
    );
  }
  const text = STATUS_TEXT[order.status];
  const step = statusStep(order.status);
  return (
    <>
      <header className="cx-top">
        <h1>{order.outlet}</h1>
      </header>
      <section className={`cx-token ${order.status}`} aria-live="polite">
        <small>Your token</small>
        <strong>{order.token}</strong>
        <div className="cx-steps" aria-hidden="true">
          {[1, 2, 3].map((n) => (
            <i key={n} className={n <= step ? 'on' : ''} />
          ))}
        </div>
        <h2>{text.title}</h2>
        <p className="muted">{text.detail}</p>
      </section>
      <ul className="cx-summary" aria-label="Your order">
        {order.items.map((i) => (
          <li key={i.name}>
            <span>
              {i.qty} × {i.name}
            </span>
          </li>
        ))}
        <li className="cx-total">
          <strong>{order.status === 'collected' ? 'Total' : 'Pay at the counter'}</strong>
          <strong className="num">{formatRupees(order.total_paise)}</strong>
        </li>
      </ul>
      {done && (
        <button className="primary" onClick={onAgain}>
          Order again
        </button>
      )}
    </>
  );
}

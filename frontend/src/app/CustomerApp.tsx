/**
 * The customer's side of a food court (README, "9.11" and "9.13").
 *
 * Sign up or log in (mobile number + password), pick a food court, browse its
 * outlets, put dishes from any of them in one cart, and place it: one order and
 * one token per outlet. Pay at each counter. /order is the front door; a court's
 * QR opens /order/<court> and skips the picker once logged in.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import {
  accountProblem,
  allItemCount,
  byCategory,
  cartCount,
  cartTotal,
  changeOutletQty,
  cleanPhone,
  courtMatches,
  grandTotal,
  ORDER_HOME,
  orderProblem,
  outletsInCart,
  soldOutInCart,
  STATUS_TEXT,
  statusStep,
  type Carts,
} from '../lib/foodcourt';
import { formatRupees } from '../lib/gst';
import {
  PublicError,
  publicApi,
  type Account,
  type CourtRow,
  type HistoryRow,
  type PublicCourt,
  type PublicMenu,
  type PublicOrder,
  type Signed,
} from '../lib/publicApi';

// ---- what the phone remembers (every read and write may fail: private windows)
const TOKEN_KEY = 'taptallow-customer-token';
const cartKey = (slug: string) => `taptallow-cart:${slug}`;
function store(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* fine: they log in or pick again */
  }
}
function recall(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function recallCarts(slug: string): Carts {
  try {
    const parsed: unknown = JSON.parse(recall(cartKey(slug)) ?? '{}');
    return parsed && typeof parsed === 'object' ? (parsed as Carts) : {};
  } catch {
    return {};
  }
}

interface Auth {
  token: string;
  account: Account;
}

/** The front door: works out who is logged in, then shows the login or the shop. */
export function CustomerApp({ slug }: { slug: string | null }) {
  const [auth, setAuth] = useState<Auth | null>(null);
  const [checked, setChecked] = useState(() => recall(TOKEN_KEY) === null);

  useEffect(() => {
    const token = recall(TOKEN_KEY);
    if (token === null) return;
    publicApi
      .me(token)
      .then((account) => setAuth({ token, account }))
      .catch((e) => {
        // Only a refused token ends the session; no signal keeps it for next time.
        if (e instanceof PublicError && e.status === 401) store(TOKEN_KEY, null);
      })
      .finally(() => setChecked(true));
  }, []);

  const signedIn = useCallback((s: Signed) => {
    store(TOKEN_KEY, s.access_token);
    setAuth({ token: s.access_token, account: s.account });
  }, []);
  const logOut = useCallback(() => {
    store(TOKEN_KEY, null);
    setAuth(null);
  }, []);

  if (!checked) {
    return (
      <main className="cx">
        <p className="muted" role="status">
          Loading…
        </p>
      </main>
    );
  }
  if (auth === null) return <AuthScreen slug={slug} onSignedIn={signedIn} />;
  if (auth.account.must_change_password) return <NewPassword auth={auth} onDone={signedIn} onLogOut={logOut} />;
  return <Shop key={auth.account.phone} slug={slug} auth={auth} onAuth={signedIn} onLogOut={logOut} />;
}

// ---------------------------------------------------------------- sign up / log in
function AuthScreen({ slug, onSignedIn }: { slug: string | null; onSignedIn(s: Signed): void }) {
  const [mode, setMode] = useState<'signup' | 'login'>('signup');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [court, setCourt] = useState<PublicCourt | null>(null);
  // Local testing only: the server says so, and then log-in asks for no password.
  const [noPassword, setNoPassword] = useState(false);

  useEffect(() => {
    if (slug) {
      publicApi
        .court(slug)
        .then((c) => {
          setCourt(c);
          document.title = c.name;
        })
        .catch(() => setCourt(null));
    }
    fetch(`${__API_URL__}/auth/dev-login`)
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .then((d: { enabled?: boolean }) => setNoPassword(d.enabled === true))
      .catch(() => setNoPassword(false));
  }, [slug]);

  const clean = cleanPhone(phone);
  const loginNeedsPassword = !(mode === 'login' && noPassword);
  const ready = clean !== null && (mode === 'login' || name.trim() !== '') && (!loginNeedsPassword || password !== '');

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || clean === null) return;
    setBusy(true);
    setError(null);
    try {
      const signed =
        mode === 'signup'
          ? await publicApi.signup(name.trim(), clean, password)
          : await publicApi.login(clean, loginNeedsPassword ? password : '-');
      onSignedIn(signed);
    } catch (err) {
      setError(err instanceof PublicError ? accountProblem(err.status, err.code, err.message) : 'No signal. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="cx">
      <header className="cx-hero">
        <small>{court ? 'Welcome to' : 'Taptallow food courts'}</small>
        <h1>{court?.name ?? 'Order from your food court'}</h1>
        <p>{court ? 'Log in to choose an outlet and order' : 'Create an account or log in to order'}</p>
      </header>
      <div className="cx-tabs" role="tablist">
        <button role="tab" aria-selected={mode === 'signup'} onClick={() => setMode('signup')}>
          Create account
        </button>
        <button role="tab" aria-selected={mode === 'login'} onClick={() => setMode('login')}>
          Log in
        </button>
      </div>
      <form className="cx-form" onSubmit={submit}>
        {mode === 'signup' && (
          <label>
            Your name
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="name" required />
          </label>
        )}
        <label>
          Mobile number
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            inputMode="tel"
            autoComplete="username"
            aria-invalid={phone !== '' && clean === null}
            required
          />
        </label>
        {phone !== '' && clean === null && <p className="error">A mobile number has 10 digits.</p>}
        {mode === 'login' && noPassword ? (
          <p className="login-test-note" role="note">
            <strong>Local test mode:</strong> no password needed to log in.
          </p>
        ) : (
          <label>
            {mode === 'signup' ? 'Choose a password' : 'Password'}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
              required
            />
          </label>
        )}
        {mode === 'signup' && (
          <p className="cx-note">
            8 or more characters. If you forget it, the food court team can give you a temporary one.
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={!ready || busy}>
          {busy ? 'Please wait…' : mode === 'signup' ? 'Create account and continue' : 'Log in'}
        </button>
      </form>
    </main>
  );
}

/** After a reset by the food court team: the temporary password must be replaced. */
function NewPassword({ auth, onDone, onLogOut }: { auth: Auth; onDone(s: Signed): void; onLogOut(): void }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await publicApi.changePassword(auth.token, current, next));
    } catch (err) {
      if (err instanceof PublicError && err.status === 401) onLogOut();
      else setError(err instanceof PublicError ? accountProblem(err.status, err.code, err.message) : 'No signal. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="cx">
      <header className="cx-top">
        <h1>Choose a new password</h1>
      </header>
      <form className="cx-form" onSubmit={submit}>
        <p className="cx-note">The food court team gave you a temporary password. Choose your own to continue.</p>
        <label>
          Temporary password
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
        </label>
        <label>
          New password
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy || current === '' || next === ''}>
          {busy ? 'Saving…' : 'Save and continue'}
        </button>
        <button type="button" className="link" onClick={onLogOut}>
          Log out
        </button>
      </form>
    </main>
  );
}

// ---------------------------------------------------------------- the signed-in shop
type Screen = { kind: 'home' } | { kind: 'court'; slug: string } | { kind: 'orders' } | { kind: 'status'; key: string };

function Shop({
  slug,
  auth,
  onAuth,
  onLogOut,
}: {
  slug: string | null;
  auth: Auth;
  onAuth(s: Signed): void;
  onLogOut(): void;
}) {
  const [screen, setScreen] = useState<Screen>(slug ? { kind: 'court', slug } : { kind: 'home' });
  const [back, setBack] = useState<Screen>({ kind: 'home' });

  // A refused token (password changed elsewhere, account switched off) ends the session.
  const guard = useCallback(
    (e: unknown) => {
      if (e instanceof PublicError && e.status === 401) onLogOut();
    },
    [onLogOut],
  );

  const goOrders = (from: Screen) => {
    setBack(from);
    setScreen({ kind: 'orders' });
  };
  const goHome = () => {
    // The QR page stays the QR page; the picker is one tap away from the court's back arrow.
    if (window.location.pathname !== ORDER_HOME) window.history.replaceState(null, '', ORDER_HOME);
    setScreen({ kind: 'home' });
  };

  return (
    <main className="cx">
      {screen.kind === 'home' ? (
        <Home auth={auth} onGuard={guard} onPick={(s) => setScreen({ kind: 'court', slug: s })} onOrders={() => goOrders(screen)} />
      ) : screen.kind === 'court' ? (
        <CourtFlow
          key={screen.slug}
          slug={screen.slug}
          auth={auth}
          onGuard={guard}
          onHome={goHome}
          onOrders={() => goOrders(screen)}
          onLogOut={onLogOut}
        />
      ) : screen.kind === 'orders' ? (
        <Orders
          auth={auth}
          onGuard={guard}
          onBack={() => setScreen(back)}
          onOpen={(key) => setScreen({ kind: 'status', key })}
          onAuth={onAuth}
          onLogOut={onLogOut}
        />
      ) : (
        <>
          <header className="cx-top">
            <button className="cx-back" onClick={() => setScreen({ kind: 'orders' })} aria-label="Back to my orders">
              ‹
            </button>
            <h1>Your order</h1>
          </header>
          <StatusCard orderKey={screen.key} />
        </>
      )}
    </main>
  );
}

function Who({ account, onOrders }: { account: Account; onOrders(): void }) {
  return (
    <div className="cx-who">
      <span>
        <strong>{account.name}</strong> · {account.phone}
      </span>
      <button onClick={onOrders}>My orders</button>
    </div>
  );
}

// ---------------------------------------------------------------- choose a food court
function Home({
  auth,
  onGuard,
  onPick,
  onOrders,
}: {
  auth: Auth;
  onGuard(e: unknown): void;
  onPick(slug: string): void;
  onOrders(): void;
}) {
  const [courts, setCourts] = useState<CourtRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');

  const load = useCallback(() => {
    publicApi
      .courts(auth.token)
      .then((r) => {
        setCourts(r.courts);
        setFailed(false);
      })
      .catch((e) => {
        onGuard(e);
        setFailed(true);
      });
  }, [auth.token, onGuard]);
  useEffect(load, [load]);

  const shown = courts?.filter((c) => courtMatches(c, query)) ?? [];
  return (
    <>
      <header className="cx-hero">
        <small>Hi {auth.account.name}</small>
        <h1>Where are you eating?</h1>
        <Who account={auth.account} onOrders={onOrders} />
      </header>
      <input
        className="cx-search"
        type="search"
        placeholder="Search food court or place"
        aria-label="Search food court or place"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {failed && !courts && (
        <p className="error" role="alert">
          Could not load the food courts. <button onClick={load}>Try again</button>
        </p>
      )}
      {courts === null && !failed && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {courts && courts.length === 0 && <p className="cx-note">No food courts are set up yet.</p>}
      {courts && courts.length > 0 && shown.length === 0 && <p className="muted">No food court matches “{query}”.</p>}
      <ul className="cx-list" aria-label="Food courts">
        {shown.map((c) => (
          <li key={c.slug}>
            <button className="cx-outlet" disabled={c.open === 0} onClick={() => onPick(c.slug)}>
              <Initials name={c.name} />
              <span className="cx-name">
                <strong>{c.name}</strong>
                {c.location && <small className="muted">{c.location}</small>}
              </span>
              <span className={`cx-tag ${c.open > 0 ? 'open' : 'shut'}`}>
                {c.open > 0 ? `${c.open} of ${c.outlets} open` : 'All closed'}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

function Initials({ name }: { name: string }) {
  return (
    <span className="cx-logo" aria-hidden="true">
      {name
        .split(/\s+/)
        .map((w) => w[0])
        .join('')
        .slice(0, 2)
        .toUpperCase()}
    </span>
  );
}

// ---------------------------------------------------------------- inside a court
interface Result {
  outletId: string;
  outlet: string;
  key?: string;
  error?: string;
}

type CourtView = 'browse' | 'cart' | 'placed';

function CourtFlow({
  slug,
  auth,
  onGuard,
  onHome,
  onOrders,
  onLogOut,
}: {
  slug: string;
  auth: Auth;
  onGuard(e: unknown): void;
  onHome(): void;
  onOrders(): void;
  onLogOut(): void;
}) {
  const [court, setCourt] = useState<PublicCourt | null>(null);
  const [missing, setMissing] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [menus, setMenus] = useState<Record<string, PublicMenu>>({});
  const [carts, setCarts] = useState<Carts>(() => recallCarts(slug));
  const [view, setView] = useState<CourtView>('browse');
  const [results, setResults] = useState<Result[]>([]);

  useEffect(() => {
    publicApi
      .court(slug)
      .then((c) => {
        setCourt(c);
        document.title = c.name;
        setActive((a) => a ?? c.outlets.find((o) => o.open)?.id ?? c.outlets[0]?.id ?? null);
      })
      .catch((e) => setMissing(e instanceof PublicError && e.status === 404));
  }, [slug]);

  const updateCarts = (next: Carts) => {
    setCarts(next);
    store(cartKey(slug), Object.keys(next).length ? JSON.stringify(next) : null);
  };

  const loadMenu = useCallback(
    (outletId: string) =>
      publicApi
        .menu(slug, outletId)
        .then((m) => {
          setMenus((all) => ({ ...all, [outletId]: m }));
          return true;
        })
        .catch(() => false),
    [slug],
  );

  if (missing) {
    return (
      <>
        <h1>We could not find this food court</h1>
        <p className="muted">Please scan the QR code again, or choose one from the list.</p>
        <button className="primary" onClick={onHome}>
          Choose a food court
        </button>
      </>
    );
  }

  const nameOf = (id: string) => court?.outlets.find((o) => o.id === id)?.name ?? 'Outlet';

  if (view === 'cart') {
    return (
      <CartScreen
        slug={slug}
        auth={auth}
        carts={carts}
        menus={menus}
        nameOf={nameOf}
        loadMenu={loadMenu}
        setCarts={updateCarts}
        onBack={() => setView('browse')}
        onGuard={onGuard}
        onLogOut={onLogOut}
        onPlaced={(r) => {
          setResults(r);
          setView('placed');
        }}
      />
    );
  }
  if (view === 'placed') {
    return (
      <Placed
        results={results}
        more={allItemCount(carts) > 0 ? 'cart' : 'browse'}
        onMore={() => setView(allItemCount(carts) > 0 ? 'cart' : 'browse')}
        onOrders={onOrders}
      />
    );
  }

  const count = allItemCount(carts);
  const total = grandTotal(menus, carts);
  const outlets = outletsInCart(carts).length;
  return (
    <>
      <header className="cx-top">
        <button className="cx-back" onClick={onHome} aria-label="Back to food courts">
          ‹
        </button>
        <h1>{court?.name ?? ' '}</h1>
      </header>
      <Who account={auth.account} onOrders={onOrders} />
      {court?.location && <p className="muted cx-where">{court.location}</p>}
      {court === null ? (
        <p className="muted" role="status">
          Loading…
        </p>
      ) : (
        <>
          <div className="cx-chips" role="tablist" aria-label="Outlets">
            {court.outlets.map((o) => {
              const n = cartCount(carts[o.id] ?? {});
              return (
                <button key={o.id} role="tab" aria-selected={active === o.id} className={o.open ? '' : 'shut'} onClick={() => setActive(o.id)}>
                  {o.name}
                  {n > 0 && <b aria-label={`${n} in cart`}>{n}</b>}
                </button>
              );
            })}
          </div>
          {active && (
            <OutletMenu
              key={active}
              slug={slug}
              outletId={active}
              menu={menus[active] ?? null}
              cart={carts[active] ?? {}}
              loadMenu={loadMenu}
              change={(itemId, delta) => updateCarts(changeOutletQty(carts, active, itemId, delta))}
            />
          )}
        </>
      )}
      {count > 0 && (
        <div className="cx-bar">
          <span>
            {count} item{count === 1 ? '' : 's'} · {outlets} outlet{outlets === 1 ? '' : 's'} · {formatRupees(total)}
          </span>
          <button className="primary" onClick={() => setView('cart')}>
            View cart
          </button>
        </div>
      )}
    </>
  );
}

function OutletMenu({
  outletId,
  menu,
  cart,
  loadMenu,
  change,
}: {
  slug: string;
  outletId: string;
  menu: PublicMenu | null;
  cart: Carts[string];
  loadMenu(id: string): Promise<boolean>;
  change(itemId: string, delta: number): void;
}) {
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    void loadMenu(outletId).then((ok) => setFailed(!ok));
  }, [loadMenu, outletId]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 60_000); // dishes sell out while people browse
    return () => window.clearInterval(timer);
  }, [load]);

  const gone = menu ? soldOutInCart(menu.items, cart) : [];
  return (
    <>
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
                      <button className="cx-add" aria-label={`Add ${i.name}`} onClick={() => change(i.id, 1)}>
                        +
                      </button>
                    ) : (
                      <span className="cx-step">
                        <button aria-label={`Remove one ${i.name}`} onClick={() => change(i.id, -1)}>
                          −
                        </button>
                        <span aria-label={`${qty} ${i.name}`}>{qty}</span>
                        <button aria-label={`Add one more ${i.name}`} onClick={() => change(i.id, 1)}>
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
          Sold out since you picked it: {gone.join(', ')}. Open your cart to remove it.
        </p>
      )}
    </>
  );
}

// ---------------------------------------------------------------- the cart: one order per outlet
function CartScreen({
  slug,
  auth,
  carts,
  menus,
  nameOf,
  loadMenu,
  setCarts,
  onBack,
  onGuard,
  onLogOut,
  onPlaced,
}: {
  slug: string;
  auth: Auth;
  carts: Carts;
  menus: Record<string, PublicMenu>;
  nameOf(id: string): string;
  loadMenu(id: string): Promise<boolean>;
  setCarts(c: Carts): void;
  onBack(): void;
  onGuard(e: unknown): void;
  onLogOut(): void;
  onPlaced(results: Result[]): void;
}) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // One id per outlet's order: tapping twice, or retrying after a bad signal, is one order.
  const requestIds = useRef<Record<string, string>>({});
  const outletIds = outletsInCart(carts);

  // Fresh menus every time the cart opens: prices and sold-out marks must be current.
  useEffect(() => {
    outletIds.forEach((id) => void loadMenu(id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ready = outletIds.every((id) => menus[id] !== undefined);
  const blocked = outletIds.some((id) => menus[id] && (!menus[id].open || soldOutInCart(menus[id].items, carts[id]).length > 0));
  const total = grandTotal(menus, carts);
  const unique = useMemo(() => (id: string) => (requestIds.current[id] ??= crypto.randomUUID()), []);

  async function place() {
    setBusy(true);
    setError(null);
    const results: Result[] = [];
    let next = carts;
    const problems: string[] = [];
    for (const id of outletIds) {
      const menu = menus[id];
      try {
        const placed = await publicApi.place(auth.token, slug, id, {
          request_id: unique(id),
          note: (notes[id] ?? '').trim(),
          message_ok: consent,
          items: menu.items.filter((i) => (carts[id][i.id] ?? 0) > 0).map((i) => ({ menu_item_id: i.id, qty: carts[id][i.id] })),
        });
        results.push({ outletId: id, outlet: nameOf(id), key: placed.status_key });
        delete requestIds.current[id];
        const { [id]: _done, ...rest } = next;
        next = rest;
      } catch (e) {
        if (e instanceof PublicError && e.status === 401) {
          onGuard(e);
          return;
        }
        const why = e instanceof PublicError ? orderProblem(e.code, e.names) : 'No signal. Please try again.';
        results.push({ outletId: id, outlet: nameOf(id), error: why });
        problems.push(`${nameOf(id)}: ${why}`);
      }
    }
    setCarts(next); // placed outlets leave the cart; the ones that failed stay to retry
    setBusy(false);
    if (results.some((r) => r.key)) onPlaced(results);
    else setError(problems.join(' '));
  }

  return (
    <>
      <header className="cx-top">
        <button className="cx-back" onClick={onBack} aria-label="Back to the menu">
          ‹
        </button>
        <h1>Your cart</h1>
      </header>
      {outletIds.length === 0 && <p className="muted">Your cart is empty.</p>}
      {outletIds.map((id) => {
        const menu = menus[id];
        const cart = carts[id];
        const gone = menu ? soldOutInCart(menu.items, cart) : [];
        return (
          <section key={id} className="cx-group" aria-label={nameOf(id)}>
            <h2>{nameOf(id)}</h2>
            {menu && !menu.open && <p className="error">This outlet is not taking orders right now. Remove its dishes to continue.</p>}
            {gone.length > 0 && <p className="error">Sold out: {gone.join(', ')}. Remove it to continue.</p>}
            <ul className="cx-summary" aria-label={`${nameOf(id)} order`}>
              {(menu?.items ?? [])
                .filter((i) => (cart[i.id] ?? 0) > 0)
                .map((i) => (
                  <li key={i.id}>
                    <span>
                      {cart[i.id]} × {i.name}
                    </span>
                    <span className="cx-step">
                      <button aria-label={`Remove one ${i.name}`} onClick={() => setCarts(changeOutletQty(carts, id, i.id, -1))}>
                        −
                      </button>
                      <button aria-label={`Add one more ${i.name}`} onClick={() => setCarts(changeOutletQty(carts, id, i.id, 1))}>
                        +
                      </button>
                    </span>
                  </li>
                ))}
              {menu && (
                <li className="cx-total">
                  <strong>Subtotal</strong>
                  <strong className="num">{formatRupees(cartTotal(menu.items, cart, menu.gst_type))}</strong>
                </li>
              )}
            </ul>
            <label>
              Note for {nameOf(id)} <span className="muted">(optional)</span>
              <input
                value={notes[id] ?? ''}
                onChange={(e) => setNotes((n) => ({ ...n, [id]: e.target.value }))}
                maxLength={120}
              />
            </label>
          </section>
        );
      })}
      {outletIds.length > 0 && (
        <form
          className="cx-form"
          onSubmit={(e) => {
            e.preventDefault();
            void place();
          }}
        >
          <div className="cx-as">
            <span className="cx-logo" aria-hidden="true">
              {auth.account.name[0]?.toUpperCase()}
            </span>
            <span>
              Ordering as <strong>{auth.account.name}</strong>
              <small className="muted"> {auth.account.phone}</small>
            </span>
            <button type="button" className="link" onClick={onLogOut}>
              Not you?
            </button>
          </div>
          <label className="cx-check">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            Message me on this number when {outletIds.length > 1 ? 'each order is' : 'my order is'} ready
          </label>
          <p className="cx-note">
            You pay <strong>{formatRupees(total)}</strong> at the counter{outletIds.length > 1 ? 's' : ''} when you collect.
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={!ready || blocked || busy}>
            {busy ? 'Placing…' : outletIds.length === 1 ? 'Place order' : `Place ${outletIds.length} orders`}
          </button>
        </form>
      )}
    </>
  );
}

/** After placing: a token per outlet that went through, and a plain note on any that did not. */
function Placed({
  results,
  more,
  onMore,
  onOrders,
}: {
  results: Result[];
  more: 'cart' | 'browse';
  onMore(): void;
  onOrders(): void;
}) {
  const placed = results.filter((r) => r.key);
  const failed = results.filter((r) => !r.key);
  return (
    <>
      <header className="cx-hero">
        <small>Order{placed.length === 1 ? '' : 's'} placed</small>
        <h1>
          {placed.length} token{placed.length === 1 ? '' : 's'}
        </h1>
        <p>Show {placed.length === 1 ? 'it' : 'each'} at {placed.length === 1 ? 'the' : 'its own'} counter</p>
      </header>
      {placed.map((r) => (
        <StatusCard key={r.key} orderKey={r.key!} />
      ))}
      {failed.map((r) => (
        <p key={r.outletId} className="error" role="alert">
          {r.outlet}: {r.error} It is still in your cart.
        </p>
      ))}
      <div className="cx-actions">
        <button className="primary" onClick={onMore}>
          {more === 'cart' ? 'Back to my cart' : 'Order more'}
        </button>
        <button onClick={onOrders}>My orders</button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- one order's live token card
function StatusCard({ orderKey: key }: { orderKey: string }) {
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

  if (lost) return <p className="error">We could not find this order.</p>;
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
    <article className="cx-card" aria-label={`Order ${order.token}`}>
      <p className="cx-outlet-name">{order.outlet}</p>
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
    </article>
  );
}

// ---------------------------------------------------------------- my orders and my account
const WHEN = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });

function Orders({
  auth,
  onGuard,
  onBack,
  onOpen,
  onAuth,
  onLogOut,
}: {
  auth: Auth;
  onGuard(e: unknown): void;
  onBack(): void;
  onOpen(key: string): void;
  onAuth(s: Signed): void;
  onLogOut(): void;
}) {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [changing, setChanging] = useState(false);

  const load = useCallback(() => {
    publicApi
      .history(auth.token)
      .then((r) => {
        setRows(r.orders);
        setFailed(false);
      })
      .catch((e) => {
        onGuard(e);
        setFailed(true);
      });
  }, [auth.token, onGuard]);
  useEffect(load, [load]);

  return (
    <>
      <header className="cx-top">
        <button className="cx-back" onClick={onBack} aria-label="Back">
          ‹
        </button>
        <h1>My orders</h1>
      </header>
      {failed && !rows && (
        <p className="error" role="alert">
          Could not load your orders. <button onClick={load}>Try again</button>
        </p>
      )}
      {rows === null && !failed && (
        <p className="muted" role="status">
          Loading…
        </p>
      )}
      {rows && rows.length === 0 && <p className="cx-note">You have not ordered yet.</p>}
      <ul className="cx-list" aria-label="Orders">
        {rows?.map((o) => (
          <li key={o.status_key}>
            <button className="cx-outlet cx-history" onClick={() => onOpen(o.status_key)}>
              <span className="cx-name">
                <strong>
                  {o.token} · {o.outlet}
                </strong>
                <small className="muted">
                  {WHEN.format(new Date(o.placed_at))} · {o.items.map((i) => `${i.qty} × ${i.name}`).join(', ')}
                </small>
              </span>
              <span className="cx-right">
                <span className={`cx-tag st-${o.status}`}>{STATUS_TEXT[o.status].title.split(',')[0]}</span>
                <small className="num">{formatRupees(o.total_paise)}</small>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <section className="cx-group" aria-label="Account">
        <h2>
          {auth.account.name} · {auth.account.phone}
        </h2>
        {changing ? (
          <ChangePassword auth={auth} onDone={(s) => (onAuth(s), setChanging(false))} onCancel={() => setChanging(false)} />
        ) : (
          <div className="cx-actions">
            <button onClick={() => setChanging(true)}>Change password</button>
            <button onClick={onLogOut}>Log out</button>
          </div>
        )}
      </section>
    </>
  );
}

function ChangePassword({ auth, onDone, onCancel }: { auth: Auth; onDone(s: Signed): void; onCancel(): void }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await publicApi.changePassword(auth.token, current, next));
    } catch (err) {
      setError(err instanceof PublicError ? accountProblem(err.status, err.code, err.message) : 'No signal. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="cx-form" onSubmit={submit}>
      <label>
        Current password
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
      </label>
      <label>
        New password
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="cx-actions">
        <button className="primary" disabled={busy || current === '' || next === ''}>
          {busy ? 'Saving…' : 'Save password'}
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

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
  cartFromLines,
  couponProblem,
  cartItems,
  changeOutletLine,
  dishCount,
  isPaused,
  lineLabel,
  pruneCart,
  saveStatus,
  savedStatus,
  unitPrice,
  type PublicItem,
  type PublicOption,
  type Cart,
  cleanPhone,
  courtMatches,
  ageText,
  grandTotal,
  notPlacedText,
  ORDER_HOME,
  orderProblem,
  outletsInCart,
  soldOutInCart,
  totalAfterOffers,
  STATUS_TEXT,
  statusStep,
  usableUsual,
  type Carts,
  type PayChoice,
} from '../lib/foodcourt';
import { chime, unlockSound } from '../lib/chime';
import { EmptyState } from './EmptyState';
import { Loading } from './Status';
import { formatRupees } from '../lib/gst';
import { enablePush, pushState, type PushState } from '../lib/push';
import { Sheet } from './Sheet';
import {
  PublicError,
  payPageUrl,
  publicApi,
  type Account,
  type CheckoutView,
  type CourtRow,
  type Favourite,
  type HistoryRow,
  type PublicCourt,
  type PublicMenu,
  type PublicOrder,
  type Signed,
  type Usual,
} from '../lib/publicApi';
import { dishDescription, dishName, getLang, t, useLang } from '../lib/i18n';
import { ALLERGENS, allergenLabel, spiceLabel, withoutAllergens } from '../lib/allergens';
import { photoSrc } from '../lib/dishPictures';
import { slotLabel, tableFromSearch, type Slot } from '../lib/pickup';
import { GroupBar } from './GroupBar';
import { OrderReceipt } from './OrderReceipt';
import { LangSwitch } from './LangSwitch';

// ---- what the phone remembers (every read and write may fail: private windows)
const TOKEN_KEY = 'taptallow-customer-token';
const cartKey = (slug: string) => `taptallow-cart:${slug}`;
// The online payment this phone is in the middle of (so closing the page does not lose it).
const pendingKey = (slug: string) => `taptallow-paying:${slug}`;
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
  useLang(); // the whole customer app redraws when the language changes
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
          {t("Loading…")}
        </p>
      </main>
    );
  }
  if (auth === null) return <AuthScreen slug={slug} onSignedIn={signedIn} />;
  if (auth.account.must_change_password) return <NewPassword auth={auth} onDone={signedIn} onLogOut={logOut} />;
  return <Shop key={auth.account.phone} slug={slug} auth={auth} onAuth={signedIn} onLogOut={logOut} />;
}

// ---------------------------------------------------------------- sign up / log in
type AuthMode = 'signup' | 'login' | 'forgot';

function AuthScreen({ slug, onSignedIn }: { slug: string | null; onSignedIn(s: Signed): void }) {
  const [mode, setModeRaw] = useState<AuthMode>('signup');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [court, setCourt] = useState<PublicCourt | null>(null);
  // Local testing only: the server says so, and then log-in asks for no password.
  const [noPassword, setNoPassword] = useState(false);
  // Phone codes: only when the server can send one (otherwise sign-up is as it always was).
  const [needCode, setNeedCode] = useState(false);
  const [step, setStep] = useState<'details' | 'code'>('details');
  const [code, setCode] = useState('');
  const [devCode, setDevCode] = useState<string | null>(null);
  const [wait, setWait] = useState(0);

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
    publicApi
      .verification()
      .then((v) => setNeedCode(v.required))
      .catch(() => setNeedCode(false));
  }, [slug]);

  // "Resend in 24s" counts down.
  useEffect(() => {
    if (wait <= 0) return;
    const timer = window.setTimeout(() => setWait((w) => w - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [wait]);

  function setMode(next: AuthMode) {
    setModeRaw(next);
    setStep('details');
    setCode('');
    setDevCode(null);
    setError(null);
  }

  const clean = cleanPhone(phone);
  const codeFlow = mode === 'forgot' || (mode === 'signup' && needCode);
  const loginNeedsPassword = !(mode === 'login' && noPassword);
  // The password box: always, except the first step of a code flow that has not got that far.
  const showPassword = mode === 'login' ? loginNeedsPassword : mode === 'signup' || step === 'code';
  const ready =
    clean !== null &&
    (mode !== 'signup' || name.trim() !== '') &&
    (step === 'details' ? (mode === 'forgot' || !showPassword || password !== '') : code.trim().length >= 4 && password !== '');

  async function ask() {
    if (clean === null) return;
    const r = await publicApi.sendCode(clean, mode === 'forgot' ? 'reset' : 'signup');
    setDevCode(r.dev_code ?? null);
    setWait(r.cooldown_seconds);
    setStep('code');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || clean === null) return;
    setBusy(true);
    setError(null);
    try {
      if (codeFlow && step === 'details') {
        await ask();
        return;
      }
      const signed =
        mode === 'signup'
          ? await publicApi.signup(name.trim(), clean, password, code.trim())
          : mode === 'forgot'
            ? await publicApi.resetPassword(clean, code.trim(), password)
            : await publicApi.login(clean, loginNeedsPassword ? password : '-');
      onSignedIn(signed);
    } catch (err) {
      setError(err instanceof PublicError ? accountProblem(err.status, err.code, err.message) : t("No signal. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setBusy(true);
    setError(null);
    try {
      await ask();
    } catch (err) {
      setError(err instanceof PublicError ? accountProblem(err.status, err.code, err.message) : t("No signal. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  const button = busy
    ? t("Please wait…")
    : mode === 'signup'
      ? step === 'details' && needCode
        ? t("Send code")
        : t("Create account and continue")
      : mode === 'forgot'
        ? step === 'details'
          ? t("Send code")
          : t("Set new password and continue")
        : t("Log in");

  return (
    <main className="cx">
      <header className="cx-hero">
        <LangSwitch />
        <small>{court ? t("Welcome to") : t("Taptallow food courts")}</small>
        <h1>{court?.name ?? t("Order from your food court")}</h1>
        <p>{court ? t("Log in to choose an outlet and order") : t("Create an account or log in to order")}</p>
      </header>
      <div className="cx-tabs" role="tablist">
        <button role="tab" aria-selected={mode === 'signup'} onClick={() => setMode('signup')}>
          {t("Create account")}
        </button>
        <button role="tab" aria-selected={mode !== 'signup'} onClick={() => setMode('login')}>
          {t("Log in")}
        </button>
      </div>
      <form className="cx-form" onSubmit={submit}>
        {mode === 'forgot' && <h2 className="cx-sub">{t("Forgot your password?")}</h2>}
        {mode === 'signup' && (
          <label>
            {t("Your name")}
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} autoComplete="name" required />
          </label>
        )}
        <label>
          {t("Mobile number")}
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            inputMode="tel"
            autoComplete="username"
            aria-invalid={phone !== '' && clean === null}
            disabled={step === 'code'}
            required
          />
        </label>
        {phone !== '' && clean === null && <p className="error">{t("A mobile number has 10 digits.")}</p>}
        {mode === 'login' && noPassword ? (
          <p className="login-test-note" role="note">
            <strong>{t("Local test mode:")}</strong> {t("no password needed to log in.")}
          </p>
        ) : (
          showPassword && (
            <label>
              {mode === 'signup' ? t("Choose a password") : mode === 'forgot' ? t("Choose a new password") : t("Password")}
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
              />
            </label>
          )
        )}
        {step === 'code' && (
          <>
            <p className="cx-note" role="status">
              {t('We sent a 6-digit code to {phone}.', { phone: clean ?? phone })}
            </p>
            {devCode && (
              <p className="login-test-note" role="note">
                <strong>{t("Local test mode:")}</strong> {t('your code is {code}.', { code: devCode })}
              </p>
            )}
            <label>
              {t("Code from the message")}
              <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} inputMode="numeric" maxLength={6} autoComplete="one-time-code" required />
            </label>
            <p className="cx-note">
              <button type="button" className="link" disabled={busy || wait > 0} onClick={() => void resend()}>
                {wait > 0 ? t('Resend in {n}s', { n: wait }) : t('Send the code again')}
              </button>{' '}
              <button type="button" className="link" onClick={() => setMode(mode)}>
                {t('Wrong number?')}
              </button>
            </p>
          </>
        )}
        {mode === 'signup' && step === 'details' && (
          <p className="cx-note">
            {needCode
              ? t("8 or more characters. We will send a code to this number to check it.")
              : t("8 or more characters. If you forget it, the food court team can give you a temporary one.")}
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={!ready || busy}>
          {button}
        </button>
        {mode === 'login' && needCode && (
          <button type="button" className="link" onClick={() => setMode('forgot')}>
            {t("Forgot your password?")}
          </button>
        )}
        {mode === 'forgot' && (
          <button type="button" className="link" onClick={() => setMode('login')}>
            {t("Back to log in")}
          </button>
        )}
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
      else setError(err instanceof PublicError ? accountProblem(err.status, err.code, err.message) : t("No signal. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="cx">
      <header className="cx-top">
        <h1>{t("Choose a new password")}</h1>
      </header>
      <form className="cx-form" onSubmit={submit}>
        <p className="cx-note">{t("The food court team gave you a temporary password. Choose your own to continue.")}</p>
        <label>
          {t("Temporary password")}
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
        </label>
        <label>
          {t("New password")}
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy || current === '' || next === ''}>
          {busy ? t("Saving…") : t("Save and continue")}
        </button>
        <button type="button" className="link" onClick={onLogOut}>
          {t("Log out")}
        </button>
      </form>
    </main>
  );
}

// ---------------------------------------------------------------- the signed-in shop
type Screen =
  | { kind: 'home' }
  | { kind: 'court'; slug: string; outlet?: string; cart?: boolean }
  | { kind: 'orders' }
  | { kind: 'status'; key: string };

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
  const [screen, setScreen] = useState<Screen>(() =>
    slug ? { kind: 'court', slug, outlet: tableFromSearch(window.location.search).outlet ?? undefined } : { kind: 'home' },
  );
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
        <Home
          auth={auth}
          onGuard={guard}
          onPick={(s) => setScreen({ kind: 'court', slug: s })}
          onPickFavourite={(f) => setScreen({ kind: 'court', slug: f.court_slug, outlet: f.outlet_id })}
          onOrders={() => goOrders(screen)}
        />
      ) : screen.kind === 'court' ? (
        <CourtFlow
          key={screen.slug}
          slug={screen.slug}
          focusOutlet={screen.outlet}
          startInCart={screen.cart === true}
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
          onReorder={(row) => {
            // Put the old order back as that outlet's cart, then open the cart: it checks the
            // outlet's menu as it loads and leaves out anything that is gone.
            const carts = { ...recallCarts(row.court_slug), [row.outlet_id]: cartFromLines(row.lines) };
            store(cartKey(row.court_slug), JSON.stringify(carts));
            setScreen({ kind: 'court', slug: row.court_slug, outlet: row.outlet_id, cart: true });
          }}
          onAuth={onAuth}
          onLogOut={onLogOut}
        />
      ) : (
        <>
          <header className="cx-top">
            <button className="cx-back" onClick={() => setScreen({ kind: 'orders' })} aria-label={t("Back to my orders")}>
              ‹
            </button>
            <h1>{t("Your order")}</h1>
          </header>
          <StatusCard orderKey={screen.key} token={auth.token} />
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
      <button onClick={onOrders}>{t("My orders")}</button>
      <LangSwitch />
    </div>
  );
}

// ---------------------------------------------------------------- choose a food court
function Home({
  auth,
  onGuard,
  onPick,
  onPickFavourite,
  onOrders,
}: {
  auth: Auth;
  onGuard(e: unknown): void;
  onPick(slug: string): void;
  onPickFavourite(f: Favourite): void;
  onOrders(): void;
}) {
  const [favs, setFavs] = useState<Favourite[]>([]);
  useEffect(() => {
    publicApi
      .favourites(auth.token)
      .then((r) => setFavs(r.favourites))
      .catch(() => undefined); // favourites are a nicety: the list of courts matters more
  }, [auth.token]);

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
        <small>{t('Hi {name}', { name: auth.account.name })}</small>
        <h1>{t("Where are you eating?")}</h1>
        <Who account={auth.account} onOrders={onOrders} />
      </header>
      <input
        className="cx-search"
        type="search"
        placeholder={t("Search food court or place")}
        aria-label={t("Search food court or place")}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {failed && !courts && (
        <p className="error" role="alert">
          {t("Could not load the food courts.")} <button onClick={load}>{t("Try again")}</button>
        </p>
      )}
      {courts === null && !failed && (
        <p className="muted" role="status">
          {t("Loading…")}
        </p>
      )}
      {favs.length > 0 && query === '' && (
        <section className="cx-group" aria-label={t("Your favourites")}>
          <h2>{t("Your favourites")}</h2>
          <ul className="cx-favs">
            {favs.map((f) => (
              <li key={f.menu_item_id}>
                <button onClick={() => onPickFavourite(f)}>
                  {f.photo_url ? <img src={photoSrc(f.photo_url, __API_URL__)} alt="" loading="lazy" /> : <span className="cx-photo" aria-hidden="true" />}
                  <span className="cx-name">
                    <strong>
                      <VegMark veg={f.is_veg} />
                      {dishName(f)}
                    </strong>
                    <small className="muted">
                      {f.outlet} · {formatRupees(f.price_paise)}
                      {f.sold_out ? t(" · sold out") : ''}
                    </small>
                  </span>
                  <span className="heart" aria-hidden="true">
                    ♥
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {courts && courts.length === 0 && <p className="cx-note">{t("No food courts are set up yet.")}</p>}
      {courts && courts.length > 0 && shown.length === 0 && <p className="muted">{t('No food court matches “{query}”.', { query })}</p>}
      <ul className="cx-list" aria-label={t("Food courts")}>
        {shown.map((c) => (
          <li key={c.slug}>
            <button className="cx-outlet" disabled={c.open === 0} onClick={() => onPick(c.slug)}>
              <Initials name={c.name} />
              <span className="cx-name">
                <strong>{c.name}</strong>
                {c.location && <small className="muted">{c.location}</small>}
              </span>
              <span className={`cx-tag ${c.open > 0 ? 'open' : 'shut'}`}>
                {c.open > 0 ? t('{open} of {outlets} open', { open: c.open, outlets: c.outlets }) : t('All closed')}
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
  id: string;
  outlet: string;
  key?: string;
  /** Why this outlet's part was not placed, in words for the customer. */
  error?: string;
}

type CourtView = 'browse' | 'cart' | 'paying' | 'placed';

function CourtFlow({
  slug,
  focusOutlet,
  startInCart,
  auth,
  onGuard,
  onHome,
  onOrders,
  onLogOut,
}: {
  slug: string;
  focusOutlet?: string;
  startInCart: boolean;
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
  const [view, setView] = useState<CourtView>(startInCart ? 'cart' : 'browse');
  const [favs, setFavs] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<Result[]>([]);
  const [paidPaise, setPaidPaise] = useState<number | null>(null);
  const [checkout, setCheckout] = useState<{ view: CheckoutView; blocked: boolean } | null>(null);

  useEffect(() => {
    publicApi
      .court(slug)
      .then((c) => {
        setCourt(c);
        document.title = c.name;
        setActive(
          (a) =>
            a ??
            (c.outlets.some((o) => o.id === focusOutlet) ? focusOutlet : undefined) ??
            c.outlets.find((o) => o.open)?.id ??
            c.outlets[0]?.id ??
            null,
        );
      })
      .catch((e) => setMissing(e instanceof PublicError && e.status === 404));
  }, [slug]);

  // Which dishes are hearted, for the hearts on the menu.
  useEffect(() => {
    publicApi
      .favourites(auth.token)
      .then((r) => setFavs(new Set(r.favourites.map((f) => f.menu_item_id))))
      .catch(() => undefined);
  }, [auth.token]);

  // A payment this phone started and did not see through (the page was closed): pick it up.
  useEffect(() => {
    const id = recall(pendingKey(slug));
    if (!id) return;
    publicApi
      .checkoutStatus(auth.token, id)
      .then((view) => {
        if (view.fulfilled) finishPaid(view);
        else {
          setCheckout({ view, blocked: false });
          setView('paying');
        }
      })
      .catch((e) => {
        onGuard(e);
        if (e instanceof PublicError && e.status === 404) store(pendingKey(slug), null);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, auth.token]);

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
        <h1>{t("We could not find this food court")}</h1>
        <p className="muted">{t("Please scan the QR code again, or choose one from the list.")}</p>
        <button className="primary" onClick={onHome}>
          {t("Choose a food court")}
        </button>
      </>
    );
  }

  const nameOf = (id: string) => court?.outlets.find((o) => o.id === id)?.name ?? t("Outlet");

  /** The payment went through and the orders were placed (or refunded): show the tokens, and take
   * what was paid for out of the cart so it cannot be ordered twice. */
  async function toggleFav(itemId: string) {
    const on = favs.has(itemId);
    setFavs((f) => {
      const next = new Set(f);
      if (on) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
    try {
      const r = await (on ? publicApi.removeFavourite(auth.token, itemId) : publicApi.addFavourite(auth.token, itemId));
      setFavs(new Set(r.favourites.map((f) => f.menu_item_id)));
    } catch (e) {
      onGuard(e);
      setFavs((f) => {
        const back = new Set(f);
        if (on) back.add(itemId);
        else back.delete(itemId);
        return back;
      });
    }
  }

  function finishPaid(view: CheckoutView) {
    const names = new Set(view.orders.map((o) => o.outlet));
    const rest = Object.fromEntries(Object.entries(carts).filter(([id]) => !names.has(nameOf(id))));
    updateCarts(rest);
    store(pendingKey(slug), null);
    setPaidPaise(view.amount_paise - view.refunded_paise);
    setResults(
      view.orders.map((o) => ({
        id: o.outlet,
        outlet: o.outlet,
        key: o.status_key ?? undefined,
        error: o.status_key ? undefined : notPlacedText(o, formatRupees(o.amount_paise)),
      })),
    );
    setCheckout(null);
    setView('placed');
  }

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
        online={court?.online_payment === true}
        onPlaced={(r) => {
          setPaidPaise(null);
          setResults(r);
          setView('placed');
        }}
        onPaying={(v, blocked) => {
          setCheckout({ view: v, blocked });
          setView('paying');
        }}
      />
    );
  }
  if (view === 'paying' && checkout) {
    return (
      <Paying
        auth={auth}
        view={checkout.view}
        blocked={checkout.blocked}
        onGuard={onGuard}
        onDone={finishPaid}
        onBack={() => {
          store(pendingKey(slug), null);
          setCheckout(null);
          setView('cart');
        }}
      />
    );
  }
  if (view === 'placed') {
    return (
      <Placed
        token={auth.token}
        results={results}
        paidPaise={paidPaise}
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
        <button className="cx-back" onClick={onHome} aria-label={t("Back to food courts")}>
          ‹
        </button>
        <h1>{court?.name ?? ' '}</h1>
      </header>
      <Who account={auth.account} onOrders={onOrders} />
      {court?.location && <p className="muted cx-where">{court.location}</p>}
      {court !== null && (
        <GroupBar
          slug={slug}
          token={auth.token}
          carts={carts}
          menus={menus}
          loadMenu={loadMenu}
          onMerge={(next) => {
            updateCarts(next);
            setView('cart');
          }}
        />
      )}
      {court === null ? (
        <p className="muted" role="status">
          {t("Loading…")}
        </p>
      ) : (
        <>
          <div className="cx-chips" role="tablist" aria-label={t("Outlets")}>
            {court.outlets.map((o) => {
              const n = cartCount(carts[o.id] ?? {});
              return (
                <button key={o.id} role="tab" aria-selected={active === o.id} className={o.open ? '' : 'shut'} onClick={() => setActive(o.id)}>
                  {o.name}
                  {n > 0 && <b aria-label={t('{n} in cart', { n })}>{n}</b>}
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
              favs={favs}
              onFav={(id) => void toggleFav(id)}
              change={(itemId, mods, delta) => updateCarts(changeOutletLine(carts, active, itemId, mods, delta))}
              token={auth.token}
              addMany={(lines) =>
                updateCarts(lines.reduce((c, l) => changeOutletLine(c, active, l.menu_item_id, l.modifier_ids, l.qty), carts))
              }
            />
          )}
        </>
      )}
      {count > 0 && (
        <div className="cx-bar">
          <span>
            {count} {count === 1 ? t('item') : t('items')} · {outlets} {outlets === 1 ? t('outlet') : t('outlets')} ·{' '}
            {formatRupees(total)}
          </span>
          <button className="primary" onClick={() => setView('cart')}>
            {t("View cart")}
          </button>
        </div>
      )}
    </>
  );
}

/** The green (vegetarian) or red (non-vegetarian) square every Indian menu uses. */
function VegMark({ veg }: { veg: boolean }) {
  return <span className={`veg ${veg ? '' : 'nv'}`} role="img" aria-label={veg ? t("Vegetarian") : t("Non-vegetarian")} />;
}

/** "Your usual": the dishes this customer keeps ordering here, one tap to fill the cart. */
function YourUsual({
  token,
  outletId,
  menu,
  cart,
  addMany,
}: {
  token: string;
  outletId: string;
  menu: PublicMenu;
  cart: Cart;
  addMany(lines: { menu_item_id: string; modifier_ids: string[]; qty: number }[]): void;
}) {
  const [usual, setUsual] = useState<Usual[]>([]);
  useEffect(() => {
    let live = true;
    publicApi.usual(token, outletId).then(
      (r) => live && setUsual(r.usual),
      () => undefined, // no usual is the same as none: the menu below still works
    );
    return () => void (live = false);
  }, [token, outletId]);
  const lines = usableUsual(menu.items, usual);
  if (lines.length === 0 || Object.keys(cart).length > 0) return null;
  const total = cartTotal(menu.items, cartFromLines(lines), menu.gst_type);
  return (
    <section className="cx-usual panel-inline" aria-label={t('Your usual')}>
      <h2>{t('Your usual')}</h2>
      <p className="muted">{t('What you keep ordering here')}</p>
      <ul>
        {lines.map((u) => (
          <li key={`${u.menu_item_id}|${u.modifier_ids.join(',')}`}>
            {u.qty} × {u.name}
          </li>
        ))}
      </ul>
      <button className="primary" onClick={() => addMany(lines)}>
        {t('Add your usual · {price}', { price: formatRupees(total) })}
      </button>
    </section>
  );
}

function OutletMenu({
  outletId,
  menu,
  cart,
  loadMenu,
  favs,
  onFav,
  change,
  token,
  addMany,
}: {
  slug: string;
  token: string;
  addMany(lines: { menu_item_id: string; modifier_ids: string[]; qty: number }[]): void;
  outletId: string;
  menu: PublicMenu | null;
  cart: Cart;
  loadMenu(id: string): Promise<boolean>;
  favs: Set<string>;
  onFav(itemId: string): void;
  change(itemId: string, mods: string[], delta: number): void;
}) {
  const [failed, setFailed] = useState(false);
  const [choosing, setChoosing] = useState<PublicItem | null>(null);
  // Allergy filter: kept for this visit only (an allergy is a health fact, not something to store).
  const [avoid, setAvoid] = useState<string[]>([]);

  const load = useCallback(() => {
    void loadMenu(outletId).then((ok) => setFailed(!ok));
  }, [loadMenu, outletId]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 60_000); // dishes sell out while people browse
    return () => window.clearInterval(timer);
  }, [load]);

  const gone = menu ? soldOutInCart(menu.items, cart) : [];
  const paused = isPaused(menu);
  return (
    <>
      {failed && !menu && (
        <p className="error" role="alert">
          {t("Could not load the menu.")} <button onClick={load}>{t("Try again")}</button>
        </p>
      )}
      {menu && !menu.open && <p className="cx-note">{t("This outlet is not taking orders right now.")}</p>}
      {menu?.open && paused && menu.paused_until && (
        <p className="cx-note" role="status">
          {t('Very busy: back at {time}', { time: slotLabel(menu.paused_until) })}
        </p>
      )}
      {menu?.open && !paused && <YourUsual token={token} outletId={outletId} menu={menu} cart={cart} addMany={addMany} />}
      {menu?.open && menu.prep_minutes && (
        <p className="muted cx-wait-note">{t('Usually ready in about {n} min', { n: menu.prep_minutes })}</p>
      )}
      {menu && menu.items.some((i) => (i.allergens ?? []).length > 0) && (
        <fieldset className="cx-avoid">
          <legend>{t('Hide dishes that contain')}</legend>
          {ALLERGENS.filter((a) => menu.items.some((i) => (i.allergens ?? []).includes(a))).map((a) => (
            <button
              key={a}
              type="button"
              className={`cx-chip ${avoid.includes(a) ? 'on' : ''}`}
              aria-pressed={avoid.includes(a)}
              onClick={() => setAvoid((v) => (v.includes(a) ? v.filter((x) => x !== a) : [...v, a]))}
            >
              {allergenLabel(a)}
            </button>
          ))}
          <small className="muted">{t('Tags are what the outlet tells us. If an allergy is serious, ask at the counter.')}</small>
        </fieldset>
      )}
      {menu &&
        byCategory(withoutAllergens(menu.items, avoid)).map((g) => (
          <section key={g.category} aria-label={t(g.category)}>
            <h2>{t(g.category)}</h2>
            <ul className="cx-list">
              {g.items.map((i) => {
                const qty = dishCount(cart, i.id);
                const hasOptions = i.options.length > 0;
                const canOrder = menu.open && !paused && !i.sold_out;
                return (
                  <li key={i.id} className={`cx-dish ${i.sold_out ? 'gone' : ''}`}>
                    {i.photo_url ? (
                      <img className="cx-photo" src={photoSrc(i.photo_url, __API_URL__)} alt="" loading="lazy" width={62} height={62} />
                    ) : null}
                    <div>
                      <strong>
                        <VegMark veg={i.is_veg} />
                        {dishName(i)}
                      </strong>
                      {dishDescription(i) && <span className="cx-desc">{dishDescription(i)}</span>}
                      {((i.allergens ?? []).length > 0 || spiceLabel(i.spice_level)) && (
                        <span className="cx-tags">
                          {(i.allergens ?? []).map((a) => (
                            <span key={a} className="cx-tag">
                              {allergenLabel(a)}
                            </span>
                          ))}
                          {spiceLabel(i.spice_level) && <span className="muted">🌶 {spiceLabel(i.spice_level)}</span>}
                        </span>
                      )}
                      {i.sold_out && <span className="muted"> {t("Sold out today")}</span>}
                      <span className="muted cx-price num">
                        {hasOptions ? t('from {price}', { price: formatRupees(i.price_paise) }) : formatRupees(i.price_paise)}
                      </span>
                    </div>
                    <button
                      className={`cx-heart ${favs.has(i.id) ? 'on' : ''}`}
                      aria-pressed={favs.has(i.id)}
                      aria-label={t(favs.has(i.id) ? 'Remove {name} from favourites' : 'Save {name} to favourites', { name: dishName(i) })}
                      onClick={() => onFav(i.id)}
                    >
                      {favs.has(i.id) ? '♥' : '♡'}
                    </button>
                    {!canOrder ? null : hasOptions ? (
                      <button className="cx-add wide" aria-label={t('Add {name}', { name: dishName(i) })} onClick={() => setChoosing(i)}>
                        {qty > 0 ? t('Add · {qty}', { qty }) : t('Add')}
                      </button>
                    ) : qty === 0 ? (
                      <button className="cx-add" aria-label={t('Add {name}', { name: dishName(i) })} onClick={() => change(i.id, [], 1)}>
                        +
                      </button>
                    ) : (
                      <span className="cx-step">
                        <button aria-label={t('Remove one {name}', { name: dishName(i) })} onClick={() => change(i.id, [], -1)}>
                          −
                        </button>
                        <span aria-label={`${qty} ${dishName(i)}`}>{qty}</span>
                        <button aria-label={t('Add one more {name}', { name: dishName(i) })} onClick={() => change(i.id, [], 1)}>
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
          {t('Sold out since you picked it: {names}. Open your cart to remove it.', { names: gone.join(', ') })}
        </p>
      )}
      {choosing && (
        <OptionsSheet
          item={choosing}
          onClose={() => setChoosing(null)}
          onAdd={(mods) => {
            change(choosing.id, mods, 1);
            setChoosing(null);
          }}
        />
      )}
    </>
  );
}

/** The options for one dish: pick a size (if it has sizes) and tick any extras, then add. The
 * price shown is only a guide: the server prices the order from its own options. */
function OptionsSheet({ item, onClose, onAdd }: { item: PublicItem; onClose(): void; onAdd(mods: string[]): void }) {
  const sizes = item.options.filter((o) => o.is_size);
  const extras = item.options.filter((o) => !o.is_size);
  const [size, setSize] = useState<string | null>(null); // null: the regular size
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const mods = [...(size ? [size] : []), ...ticked];
  const delta = (o: PublicOption) => (o.price_delta_paise ? ` ${o.price_delta_paise > 0 ? '+' : '−'}${formatRupees(Math.abs(o.price_delta_paise))}` : '');

  return (
    <Sheet title={dishName(item)} onClose={onClose}>
      <div className="cx-form">
        {dishDescription(item) && <p className="muted">{dishDescription(item)}</p>}
        {sizes.length > 0 && (
          <fieldset className="cx-opts">
            <legend>{t("Size")}</legend>
            <label className={`cx-chip ${size === null ? 'on' : ''}`}>
              <input type="radio" name="size" checked={size === null} onChange={() => setSize(null)} />
              {t("Regular")}
            </label>
            {sizes.map((o) => (
              <label key={o.id} className={`cx-chip ${size === o.id ? 'on' : ''}`}>
                <input type="radio" name="size" checked={size === o.id} onChange={() => setSize(o.id)} />
                {t(o.name)}
                {delta(o)}
              </label>
            ))}
          </fieldset>
        )}
        {extras.length > 0 && (
          <fieldset className="cx-opts">
            <legend>{t("Make it")}</legend>
            {extras.map((o) => (
              <label key={o.id} className={`cx-chip ${ticked.has(o.id) ? 'on' : ''}`}>
                <input
                  type="checkbox"
                  checked={ticked.has(o.id)}
                  onChange={() =>
                    setTicked((prev) => {
                      const next = new Set(prev);
                      if (next.has(o.id)) next.delete(o.id);
                      else next.add(o.id);
                      return next;
                    })
                  }
                />
                {t(o.name)}
                {delta(o)}
              </label>
            ))}
          </fieldset>
        )}
        <button className="primary" onClick={() => onAdd(mods)}>
          {t('Add to cart · {price}', { price: formatRupees(unitPrice(item, mods)) })}
        </button>
      </div>
    </Sheet>
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
  online,
  onPlaced,
  onPaying,
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
  online: boolean;
  onPlaced(results: Result[]): void;
  onPaying(view: CheckoutView, blocked: boolean): void;
}) {
  const [pay, setPay] = useState<PayChoice>(online ? 'online' : 'counter');
  const checkoutRef = useRef<{ key: string; id: string } | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // "When do you want it?": a slot per outlet, or null for as soon as possible.
  const [pickups, setPickups] = useState<Record<string, string | null>>({});
  const [slotLists, setSlotLists] = useState<Record<string, Slot[]>>({});
  // A table's QR names the table (and the outlet it belongs to): the order says "bring it to Table 4".
  const [scanned] = useState(() => tableFromSearch(window.location.search));
  const tableFor = (id: string) => (scanned.table && (scanned.outlet === null || scanned.outlet === id) ? scanned.table : '');
  // One id per outlet's order: tapping twice, or retrying after a bad signal, is one order.
  const requestIds = useRef<Record<string, string>>({});
  const outletIds = outletsInCart(carts);

  // Fresh menus every time the cart opens: prices and sold-out marks must be current.
  useEffect(() => {
    outletIds.forEach((id) => void loadMenu(id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    outletIds.forEach((id) => {
      publicApi.slots(slug, id).then(
        (r) => setSlotLists((l) => ({ ...l, [id]: r.enabled ? r.slots : [] })),
        () => undefined, // no slots to offer is the same as "as soon as possible" only
      );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ready = outletIds.every((id) => menus[id] !== undefined);
  const [notice, setNotice] = useState<string | null>(null);
  const pruned = useRef(false);

  // "Order again" can meet a changed menu: once every menu has loaded, take out what is gone and say so.
  useEffect(() => {
    if (!ready || pruned.current || outletIds.length === 0) return;
    pruned.current = true;
    let next = carts;
    let dropped = 0;
    for (const id of outletIds) {
      const r = pruneCart(menus[id].items, carts[id]);
      dropped += r.dropped;
      next = r.dropped > 0 ? { ...next, [id]: r.cart } : next;
    }
    if (dropped > 0) {
      setCarts(Object.fromEntries(Object.entries(next).filter(([, c]) => Object.keys(c).length > 0)));
      setNotice(
        dropped === 1
          ? t('{n} dish is no longer on the menu and was left out.', { n: dropped })
          : t('{n} dishes are no longer on the menu and were left out.', { n: dropped }),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);
  const blocked = outletIds.some((id) => menus[id] && (!menus[id].open || isPaused(menus[id]) || soldOutInCart(menus[id].items, carts[id]).length > 0));
  // Offers: the code typed per outlet, and the ones the server has checked for exactly this cart.
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [applied, setApplied] = useState<Record<string, { code: string; before: number; total: number; sig: string } | undefined>>({});
  const [codeError, setCodeError] = useState<Record<string, string | undefined>>({});
  const cartSig = (id: string) => JSON.stringify(cartItems(carts[id] ?? {}));
  // A code was checked for one cart: when the dishes change, it must be checked again.
  const live = (id: string) => (applied[id] && applied[id]!.sig === cartSig(id) ? applied[id] : undefined);
  const offers = Object.fromEntries(outletIds.map((id) => [id, live(id)]));
  const total = totalAfterOffers(menus, carts, offers);
  async function applyCode(id: string) {
    const code = (codes[id] ?? '').trim();
    if (!code) return;
    setCodeError((e) => ({ ...e, [id]: undefined }));
    try {
      const r = await publicApi.couponCheck(auth.token, { slug, outlet_id: id, code, items: cartItems(carts[id]) });
      const before = cartTotal(menus[id].items, carts[id], menus[id].gst_type);
      setApplied((a) => ({ ...a, [id]: { code, before, total: r.total_paise, sig: cartSig(id) } }));
    } catch (e) {
      if (e instanceof PublicError && e.status === 401) return onGuard(e);
      setApplied((a) => ({ ...a, [id]: undefined }));
      setCodeError((c) => ({ ...c, [id]: e instanceof PublicError ? couponProblem(e.code, e.message) : t('No signal. Please try again.') }));
    }
  }
  const unique = useMemo(() => (id: string) => (requestIds.current[id] ??= crypto.randomUUID()), []);

  async function place() {
    setBusy(true);
    setError(null);
    const results: Result[] = [];
    let next = carts;
    const problems: string[] = [];
    for (const id of outletIds) {
      try {
        const placed = await publicApi.place(auth.token, slug, id, {
          request_id: unique(id),
          note: (notes[id] ?? '').trim(),
          message_ok: consent,
          pickup_at: pickups[id] ?? null,
          table_name: tableFor(id),
          coupon_code: offers[id]?.code ?? '',
          items: cartItems(carts[id]),
        });
        results.push({ id, outlet: nameOf(id), key: placed.status_key });
        delete requestIds.current[id];
        const { [id]: _done, ...rest } = next;
        next = rest;
      } catch (e) {
        if (e instanceof PublicError && e.status === 401) {
          onGuard(e);
          return;
        }
        const why = e instanceof PublicError ? orderProblem(e.code, e.names) : t("No signal. Please try again.");
        results.push({ id, outlet: nameOf(id), error: why });
        problems.push(`${nameOf(id)}: ${why}`);
      }
    }
    setCarts(next); // placed outlets leave the cart; the ones that failed stay to retry
    setBusy(false);
    if (results.some((r) => r.key)) onPlaced(results);
    else setError(problems.join(' '));
  }

  async function payOnline() {
    setBusy(true);
    setError(null);
    // The payment page opens in a new tab. It is opened here, in the tap itself, so the browser
    // allows it; it is pointed at Razorpay once the server has made the payment.
    const popup = window.open('about:blank', '_blank');
    const orders = outletIds.map((id) => ({
      outlet_id: id,
      request_id: unique(id),
      note: (notes[id] ?? '').trim(),
      pickup_at: pickups[id] ?? null,
      table_name: tableFor(id),
      coupon_code: offers[id]?.code ?? '',
      items: cartItems(carts[id]),
    }));
    // A new payment whenever the cart changes: one id must never mean two different carts.
    const key = JSON.stringify([orders.map((o) => [o.outlet_id, o.items, o.note, o.pickup_at, o.table_name, o.coupon_code]), consent]);
    if (checkoutRef.current === null || checkoutRef.current.key !== key) {
      checkoutRef.current = { key, id: crypto.randomUUID() };
    }
    try {
      const view = await publicApi.checkout(auth.token, {
        checkout_id: checkoutRef.current.id,
        slug,
        message_ok: consent,
        orders,
      });
      store(pendingKey(slug), view.id);
      if (popup) popup.location.href = payPageUrl(view.razorpay_order_id);
      onPaying(view, popup === null);
    } catch (e) {
      popup?.close();
      if (e instanceof PublicError && e.status === 401) {
        onGuard(e);
        return;
      }
      setError(e instanceof PublicError ? e.message || orderProblem(e.code, e.names) : t("No signal. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="cx-top">
        <button className="cx-back" onClick={onBack} aria-label={t("Back to the menu")}>
          ‹
        </button>
        <h1>{t("Your cart")}</h1>
      </header>
      {notice && (
        <p className="cx-note" role="status">
          {notice}
        </p>
      )}
      {outletIds.length === 0 && <p className="muted">{t("Your cart is empty.")}</p>}
      {outletIds.map((id) => {
        const menu = menus[id];
        const cart = carts[id];
        const gone = menu ? soldOutInCart(menu.items, cart) : [];
        return (
          <section key={id} className="cx-group" aria-label={nameOf(id)}>
            <h2>{nameOf(id)}</h2>
            {menu && !menu.open && <p className="error">{t("This outlet is not taking orders right now. Remove its dishes to continue.")}</p>}
            {gone.length > 0 && <p className="error">{t('Sold out: {names}. Remove it to continue.', { names: gone.join(', ') })}</p>}
            <ul className="cx-summary" aria-label={t('{name} order', { name: nameOf(id) })}>
              {menu &&
                Object.values(cart).map((line) => {
                  const item = menu.items.find((i) => i.id === line.itemId);
                  if (!item) return null;
                  const label = lineLabel(item, line.mods);
                  return (
                    <li key={`${line.itemId}|${line.mods.join(',')}`}>
                      <span>
                        {line.qty} × {label}
                      </span>
                      <span className="cx-step">
                        <button
                          aria-label={t('Remove one {name}', { name: label })}
                          onClick={() => setCarts(changeOutletLine(carts, id, line.itemId, line.mods, -1))}
                        >
                          −
                        </button>
                        <button
                          aria-label={t('Add one more {name}', { name: label })}
                          onClick={() => setCarts(changeOutletLine(carts, id, line.itemId, line.mods, 1))}
                        >
                          +
                        </button>
                      </span>
                    </li>
                  );
                })}
              {menu && (
                <li className="cx-total">
                  <strong>{t("Subtotal")}</strong>
                  <strong className="num">{formatRupees(cartTotal(menu.items, cart, menu.gst_type))}</strong>
                </li>
              )}
            </ul>
            <label>
              {t('Note for {name} (optional)', { name: nameOf(id) })}
              <input
                value={notes[id] ?? ''}
                onChange={(e) => setNotes((n) => ({ ...n, [id]: e.target.value }))}
                maxLength={120}
              />
            </label>
            <div className="cx-code">
              <label>
                {t('Offer code (optional)')}
                <input
                  value={codes[id] ?? ''}
                  onChange={(e) => setCodes((c) => ({ ...c, [id]: e.target.value.toUpperCase() }))}
                  maxLength={30}
                  autoCapitalize="characters"
                />
              </label>
              <button type="button" disabled={!(codes[id] ?? '').trim()} onClick={() => void applyCode(id)}>
                {t('Apply')}
              </button>
              {codeError[id] && (
                <p className="error" role="alert">
                  {codeError[id]}
                </p>
              )}
              {offers[id] && (
                <p className="cx-note" role="status">
                  {t('Code {code} applied: you save {amount}', {
                    code: offers[id]!.code.toUpperCase(),
                    amount: formatRupees(offers[id]!.before - offers[id]!.total),
                  })}
                </p>
              )}
            </div>
            {tableFor(id) && (
              <p className="cx-note" role="status">
                {t('Your order will be brought to {table}.', { table: tableFor(id) })}
              </p>
            )}
            {(slotLists[id] ?? []).length > 0 && (
              <fieldset className="cx-slots">
                <legend>{t('When do you want it?')}</legend>
                <button
                  type="button"
                  className={`cx-chip ${(pickups[id] ?? null) === null ? 'on' : ''}`}
                  aria-pressed={(pickups[id] ?? null) === null}
                  onClick={() => setPickups((p) => ({ ...p, [id]: null }))}
                >
                  {t('As soon as possible')}
                </button>
                {slotLists[id].map((sl) => (
                  <button
                    key={sl.at}
                    type="button"
                    className={`cx-chip ${pickups[id] === sl.at ? 'on' : ''}`}
                    aria-pressed={pickups[id] === sl.at}
                    disabled={sl.full}
                    onClick={() => setPickups((p) => ({ ...p, [id]: sl.at }))}
                  >
                    {slotLabel(sl.at)}
                    {sl.full ? ` (${t('full')})` : ''}
                  </button>
                ))}
                <small className="muted">{t('Times are 15 minutes apart. The outlet starts your order just before your time.')}</small>
              </fieldset>
            )}
          </section>
        );
      })}
      {outletIds.length > 0 && (
        <form
          className="cx-form"
          onSubmit={(e) => {
            e.preventDefault();
            void (pay === 'online' ? payOnline() : place());
          }}
        >
          <div className="cx-as">
            <span className="cx-logo" aria-hidden="true">
              {auth.account.name[0]?.toUpperCase()}
            </span>
            <span>
              {t("Ordering as")} <strong>{auth.account.name}</strong>
              <small className="muted"> {auth.account.phone}</small>
            </span>
            <button type="button" className="link" onClick={onLogOut}>
              {t("Not you?")}
            </button>
          </div>
          <label className="cx-check">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            {outletIds.length > 1
              ? t('Message me on this number when each order is ready')
              : t('Message me on this number when my order is ready')}
          </label>
          {online && (
            <fieldset className="cx-pay">
              <legend>{t("How do you want to pay?")}</legend>
              <label className={`cx-opt ${pay === 'online' ? 'on' : ''}`}>
                <input type="radio" name="pay" checked={pay === 'online'} onChange={() => setPay('online')} />
                <span>
                  <strong>{t('Pay online · {amount}', { amount: formatRupees(total) })}</strong>
                  <small>{outletIds.length > 1 ? t('UPI or card, one payment for all outlets') : t('UPI or card')}</small>
                </span>
              </label>
              <label className={`cx-opt ${pay === 'counter' ? 'on' : ''}`}>
                <input type="radio" name="pay" checked={pay === 'counter'} onChange={() => setPay('counter')} />
                <span>
                  <strong>{outletIds.length > 1 ? t('Pay at the counters') : t('Pay at the counter')}</strong>
                  <small>{outletIds.length > 1 ? t('Pay each outlet when you collect') : t('Pay there when you collect')}</small>
                </span>
              </label>
            </fieldset>
          )}
          {pay === 'online' ? (
            <p className="cx-note">{t("Nothing is sent to the kitchen until your payment goes through.")}</p>
          ) : (
            <p className="cx-note">
              {outletIds.length > 1
                ? t('You pay {amount} at the counters when you collect.', { amount: formatRupees(total) })
                : t('You pay {amount} at the counter when you collect.', { amount: formatRupees(total) })}
            </p>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={!ready || blocked || busy}>
            {busy
              ? pay === 'online'
                ? t("Starting payment…")
                : t("Placing…")
              : pay === 'online'
                ? outletIds.length === 1
                  ? t('Pay {amount} and place order', { amount: formatRupees(total) })
                  : t('Pay {amount} and place {n} orders', { amount: formatRupees(total), n: outletIds.length })
                : outletIds.length === 1
                  ? t('Place order')
                  : t('Place {n} orders', { n: outletIds.length })}
          </button>
        </form>
      )}
    </>
  );
}

/** The payment screen: Razorpay is open in another tab; this page checks by itself. */
function Paying({
  auth,
  view: first,
  blocked,
  onGuard,
  onDone,
  onBack,
}: {
  auth: Auth;
  view: CheckoutView;
  blocked: boolean;
  onGuard(e: unknown): void;
  onDone(view: CheckoutView): void;
  onBack(): void;
}) {
  const [view, setView] = useState(first);
  const [lost, setLost] = useState(false);

  useEffect(() => {
    let live = true;
    const poll = () =>
      publicApi
        .checkoutStatus(auth.token, first.id)
        .then((v) => {
          if (!live) return;
          setLost(false);
          setView(v);
          if (v.fulfilled) onDone(v);
        })
        .catch((e) => {
          if (!live) return;
          onGuard(e);
          setLost(true); // no signal: keep trying, the payment is safe on the server
        });
    const timer = window.setInterval(poll, 3000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [first.id, auth.token]);

  return (
    <>
      <header className="cx-top">
        <button className="cx-back" onClick={onBack} aria-label={t("Cancel and go back to the cart")}>
          ‹
        </button>
        <h1>{t("Paying")} {formatRupees(view.amount_paise)}</h1>
      </header>
      <section className="cx-group cx-wait" role="status" aria-live="polite">
        {view.status === 'paid' ? (
          <>
            <h2>{t("Payment received")}</h2>
            <p className="muted">{t("Placing your orders…")}</p>
          </>
        ) : (
          <>
            <div className="cx-spin" aria-hidden="true" />
            <h2>{t("Waiting for your payment")}</h2>
            <p className="muted">{t("Finish paying in the other tab. This page moves on by itself.")}</p>
            {view.status === 'failed' && (
              <p className="error">
                {view.error
                  ? t('The payment did not go through: {why}. You can try again.', { why: view.error })
                  : t('The payment did not go through. You can try again.')}
              </p>
            )}
            {blocked && <p className="cx-note">{t("Your browser blocked the payment page. Use the button below to open it.")}</p>}
            <a className="button" href={payPageUrl(view.razorpay_order_id)} target="_blank" rel="noreferrer">
              {blocked ? t("Open the payment page") : t("Open the payment page again")}
            </a>
            <p className="muted">
              {t("Closed it by mistake? Nothing is charged until you pay. If money left your account, your tokens will appear here.")}
            </p>
            {lost && <p className="muted">{t("No signal. Still trying…")}</p>}
          </>
        )}
      </section>
      <button className="link" onClick={onBack}>
        {t("Cancel and go back to the cart")}
      </button>
    </>
  );
}

/** After placing: a token per outlet that went through, and a plain note on any that did not. */
function Placed({
  token,
  results,
  paidPaise,
  more,
  onMore,
  onOrders,
}: {
  token: string;
  results: Result[];
  paidPaise: number | null;
  more: 'cart' | 'browse';
  onMore(): void;
  onOrders(): void;
}) {
  const placed = results.filter((r) => r.key);
  const failed = results.filter((r) => !r.key);
  return (
    <>
      <header className="cx-hero">
        <small>
          {paidPaise !== null && paidPaise > 0
            ? t('Paid {amount} online', { amount: formatRupees(paidPaise) })
            : placed.length === 1
              ? t('Order placed')
              : t('Orders placed')}
        </small>
        <h1>
          {placed.length} {placed.length === 1 ? t('token') : t('tokens')}
        </h1>
        <p>
          {placed.length === 0
            ? t('Nothing was placed')
            : placed.length === 1
              ? t('Show it at the counter')
              : t('Show each at its own counter')}
        </p>
      </header>
      {placed.map((r) => (
        <StatusCard key={r.key} orderKey={r.key!} token={token} />
      ))}
      {failed.map((r) => (
        <p key={r.id} className="cx-note" role="alert">
          {paidPaise !== null ? r.error : t('{outlet}: {error} It is still in your cart.', { outlet: r.outlet, error: r.error ?? '' })}
        </p>
      ))}
      <div className="cx-actions">
        <button className="primary" onClick={onMore}>
          {more === 'cart' ? t("Back to my cart") : t("Order more")}
        </button>
        <button onClick={onOrders}>{t("My orders")}</button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- one order's live token card
function StatusCard({ orderKey: key, token }: { orderKey: string; token: string }) {
  const saved = useMemo(() => savedStatus<PublicOrder>(key), [key]);
  const [order, setOrder] = useState<PublicOrder | null>(saved?.order ?? null);
  const [lost, setLost] = useState(false);
  // When the shown state was last confirmed by the server; set while the phone has no signal.
  const [seenAt, setSeenAt] = useState<number>(saved?.at ?? 0);
  const [offline, setOffline] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const last = useRef<string | null>(saved?.order.status ?? null);

  const done = order?.status === 'collected' || order?.status === 'declined';

  useEffect(() => {
    let live = true;
    const poll = () =>
      publicApi
        .order(key)
        .then((o) => {
          if (!live) return;
          // The moment it turns ready while this page is open: a chime, a buzz and the tab title.
          if (o.status === 'ready' && last.current !== null && last.current !== 'ready') {
            chime();
            document.title = t('🔔 {token} is ready', { token: o.token });
          }
          last.current = o.status;
          setOrder(o);
          setLost(false);
          setOffline(false);
          setSeenAt(Date.now());
          saveStatus(key, o);
        })
        .catch((e) => {
          if (!live) return;
          if (e instanceof PublicError && e.status === 404) setLost(true);
          else setOffline(true); // no signal, or the server is busy: keep what we have and keep trying
        });
    void poll();
    if (done) return () => void (live = false);
    const timer = window.setInterval(poll, 5000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [key, done]);

  useEffect(() => {
    if (!offline) return;
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, [offline]);

  if (lost) return <p className="error">{t("We could not find this order.")}</p>;
  if (!order) {
    return (
      <p className="muted" role="status">
        {t("Loading your order…")}
      </p>
    );
  }
  const text = STATUS_TEXT[order.status];
  const step = statusStep(order.status);
  return (
    <article className="cx-card" aria-label={t('Order {token}', { token: order.token })}>
      <p className="cx-outlet-name">{order.outlet}</p>
      {offline && (
        <p className="cx-note" role="status">
          📴 {t('No signal. Last updated {when}. We keep trying.', { when: ageText(now - seenAt) })}
        </p>
      )}
      <section className={`cx-token ${order.status}`} aria-live="polite">
        <small>{t("Your token")}</small>
        <strong>{order.token}</strong>
        <div className="cx-steps" aria-hidden="true">
          {[1, 2, 3].map((n) => (
            <i key={n} className={n <= step ? 'on' : ''} />
          ))}
        </div>
        <h2>{t(text.title)}</h2>
        <p className="muted">{t(text.detail)}</p>
        {order.status === 'received' && order.prep_minutes && (
          <p className="muted">{t('Usually ready in about {n} min', { n: order.prep_minutes })}</p>
        )}
      </section>
      {!done && <NotifyPrompt token={token} />}
      {order.status === 'collected' && <RateOrder token={token} orderKey={key} />}
      <ul className="cx-summary" aria-label={t("Your order")}>
        {order.items.map((i) => (
          <li key={i.name}>
            <span>
              {i.qty} × {i.name}
            </span>
          </li>
        ))}
        <li className="cx-total">
          <strong>{order.paid_online ? t("Paid online") : order.status === 'collected' ? t("Total") : t("Pay at the counter")}</strong>
          <strong className="num">{formatRupees(order.total_paise)}</strong>
        </li>
      </ul>
    </article>
  );
}

/** "Tell me when it is ready" for people who will close the page. Only shown when the server has
 * notification keys, the browser can do it, and the customer has not already said yes or no. */
function NotifyPrompt({ token }: { token: string }) {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    void pushState(token).then((s) => live && setState(s));
    return () => void (live = false);
  }, [token]);

  if (state === 'on') return <p className="muted cx-notify">{t("🔔 We will notify you when it is ready.")}</p>;
  if (state !== 'ask') return null;
  return (
    <div className="cx-notify-card">
      <div>
        <strong>{t("Get a notification when it is ready")}</strong>
        <span className="muted">{t("So you can close this page and do something else.")}</span>
      </div>
      <button
        className="primary"
        disabled={busy}
        onClick={() => {
          unlockSound(); // the same tap lets this page chime too
          setBusy(true);
          void enablePush(token).then((s) => {
            setState(s);
            setBusy(false);
          });
        }}
      >
        {t("Allow notifications")}
      </button>
    </div>
  );
}

/** One tap to rate a collected order, once. */
function RateOrder({ token, orderKey }: { token: string; orderKey: string }) {
  const [mine, setMine] = useState<{ rating: number | null; comment: string } | null>(null);
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    publicApi
      .myRating(token, orderKey)
      .then((r) => live && setMine(r))
      .catch(() => undefined);
    return () => void (live = false);
  }, [token, orderKey]);

  if (mine === null) return null;
  if (mine.rating !== null) {
    return (
      <p className="cx-rated" role="status">
        {t('Thanks for rating: {stars}', { stars: '★'.repeat(mine.rating) + '☆'.repeat(5 - mine.rating) })}
      </p>
    );
  }
  return (
    <form
      className="cx-rate"
      onSubmit={(e) => {
        e.preventDefault();
        if (stars === 0) return;
        setBusy(true);
        setError(null);
        publicApi
          .rate(token, orderKey, stars, comment.trim())
          .then(() => setMine({ rating: stars, comment: comment.trim() }))
          .catch(() => setError(t("Could not send your rating. Please try again.")))
          .finally(() => setBusy(false));
      }}
    >
      <strong>{t("How was it?")}</strong>
      <div className="cx-stars" role="radiogroup" aria-label={t("Your rating")}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={stars === n}
            aria-label={n === 1 ? t('{n} star', { n }) : t('{n} stars', { n })}
            className={n <= stars ? 'on' : ''}
            onClick={() => setStars(n)}
          >
            ★
          </button>
        ))}
      </div>
      <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={200} placeholder={t("Anything to add? (optional)")} />
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={stars === 0 || busy}>
        {busy ? t("Sending…") : t("Send")}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------- my orders and my account
const when = (d: Date) =>
  new Intl.DateTimeFormat(getLang() === 'ta' ? 'ta-IN' : 'en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d);

function Orders({
  auth,
  onGuard,
  onBack,
  onOpen,
  onReorder,
  onAuth,
  onLogOut,
}: {
  auth: Auth;
  onGuard(e: unknown): void;
  onBack(): void;
  onOpen(key: string): void;
  onReorder(row: HistoryRow): void;
  onAuth(s: Signed): void;
  onLogOut(): void;
}) {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [changing, setChanging] = useState(false);
  const [receipt, setReceipt] = useState<HistoryRow | null>(null);
  const [rewards, setRewards] = useState<{ code: string; outlet: string; off_paise: number; valid_until: string | null }[]>([]);

  useEffect(() => {
    publicApi
      .rewards(auth.token)
      .then((r) => setRewards(r.rewards))
      .catch(() => setRewards([])); // a reward list that will not load is not worth an error
  }, [auth.token]);

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
        <button className="cx-back" onClick={onBack} aria-label={t("Back")}>
          ‹
        </button>
        <h1>{t("My orders")}</h1>
      </header>
      {failed && !rows && (
        <p className="error" role="alert">
          {t("Could not load your orders.")} <button onClick={load}>{t("Try again")}</button>
        </p>
      )}
      {rows === null && !failed && <Loading />}
      {rewards.length > 0 && (
        <section className="cx-rewards" aria-label={t("Your rewards")}>
          <h2>{t("Your rewards")}</h2>
          <ul>
            {rewards.map((r) => (
              <li key={r.code}>
                <strong>{t("{amount} off your next order at {outlet}", { amount: formatRupees(r.off_paise), outlet: r.outlet })}</strong>
                <small className="muted">
                  {t("Code {code}", { code: r.code })}
                  {r.valid_until ? ` · ${t("use by {date}", { date: r.valid_until })}` : ''}
                </small>
              </li>
            ))}
          </ul>
        </section>
      )}
      {rows && rows.length === 0 && (
        <EmptyState
          title={t("You have not ordered yet.")}
          hint={t("Your orders and rewards will show up here.")}
        />
      )}
      <ul className="cx-list" aria-label={t("Orders")}>
        {rows?.map((o) => (
          <li key={o.status_key} className="cx-order-row">
            <button className="cx-outlet cx-history" onClick={() => onOpen(o.status_key)}>
              <span className="cx-name">
                <strong>
                  {o.token} · {o.outlet}
                </strong>
                <small className="muted">
                  {when(new Date(o.placed_at))} · {o.items.map((i) => `${i.qty} × ${i.name}`).join(', ')}
                </small>
              </span>
              <span className="cx-right">
                <span className={`cx-tag st-${o.status}`}>{t(STATUS_TEXT[o.status].title).split(/[,،]/)[0]}</span>
                <small className="num">{formatRupees(o.total_paise)}</small>
                {o.rating !== null && (
                  <small className="cx-rated" aria-label={t('You rated it {n} out of 5', { n: o.rating })}>
                    {'★'.repeat(o.rating)}
                  </small>
                )}
              </span>
            </button>
            <button className="cx-again" onClick={() => setReceipt(o)} aria-label={t('Receipt for {token}', { token: o.token })}>
              {t('Receipt')}
            </button>
            {o.lines.length > 0 && (
              <button className="cx-again" onClick={() => onReorder(o)} aria-label={t('Order {token} again', { token: o.token })}>
                {t("↻ Order again")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {receipt && <OrderReceipt order={receipt} onClose={() => setReceipt(null)} />}
      <section className="cx-group" aria-label={t("Account")}>
        <h2>
          {auth.account.name} · {auth.account.phone}
        </h2>
        {changing ? (
          <ChangePassword auth={auth} onDone={(s) => (onAuth(s), setChanging(false))} onCancel={() => setChanging(false)} />
        ) : (
          <div className="cx-actions">
            <button onClick={() => setChanging(true)}>{t("Change password")}</button>
            <button onClick={onLogOut}>{t("Log out")}</button>
          </div>
        )}
        <DeleteAccount auth={auth} onDeleted={onLogOut} />
      </section>
    </>
  );
}

/** "Delete my account": says plainly what goes and what stays, then needs the password. */
function DeleteAccount({ auth, onDeleted }: { auth: Auth; onDeleted(): void }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function erase() {
    setBusy(true);
    setError(null);
    try {
      await publicApi.deleteAccount(auth.token, password);
      onDeleted();
    } catch (e) {
      setError(
        e instanceof PublicError && e.status === 403 ? t('That password is not right.') : t('Could not delete the account. Please try again.'),
      );
    } finally {
      setBusy(false);
    }
  }
  if (!open) {
    return (
      <button className="link danger" onClick={() => setOpen(true)}>
        {t('Delete my account')}
      </button>
    );
  }
  return (
    <form
      className="cx-delete"
      onSubmit={(e) => {
        e.preventDefault();
        void erase();
      }}
    >
      <p>
        <strong>{t('This cannot be undone.')}</strong>{' '}
        {t('Your login, name, number, favourites and notifications are removed. The outlets you ordered from keep a record of past orders for their books (what was ordered, when, and the name and number you gave), because they must keep sales records.')}
      </p>
      <label>
        {t('Your password')}
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="cx-actions">
        <button className="danger" disabled={busy || password === ''}>
          {t('Yes, delete my account')}
        </button>
        <button type="button" onClick={() => setOpen(false)}>
          {t('Keep my account')}
        </button>
      </div>
    </form>
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
      setError(err instanceof PublicError ? accountProblem(err.status, err.code, err.message) : t("No signal. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="cx-form" onSubmit={submit}>
      <label>
        {t("Current password")}
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required />
      </label>
      <label>
        {t("New password")}
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="cx-actions">
        <button className="primary" disabled={busy || current === '' || next === ''}>
          {busy ? t("Saving…") : t("Save password")}
        </button>
        <button type="button" onClick={onCancel}>
          {t("Cancel")}
        </button>
      </div>
    </form>
  );
}

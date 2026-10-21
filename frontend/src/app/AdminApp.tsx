/**
 * The super admin's page (/admin): make food courts and put outlets in them. A separate
 * sign-in from the shop app's; its token is of a different type that no shop screen
 * accepts, and a shop owner's login cannot open this (README, "9.12").
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { cleanPhone, courtPath } from '../lib/foodcourt';
import { AdminError, adminApi, devLoginOn, saveToken, savedToken, type AdminCourt } from '../lib/adminApi';
import { Qr } from './Qr';
import { Sheet } from './Sheet';

export function AdminApp() {
  const [token, setToken] = useState<string | null>(() => savedToken());
  const [name, setName] = useState('');

  useEffect(() => {
    document.title = 'Taptallow · Platform admin';
  }, []);

  const signOut = useCallback(() => {
    saveToken(null);
    setToken(null);
  }, []);

  return (
    <main className="admin">
      <header className="admin-bar">
        <strong>Taptallow · Platform admin</strong>
        {token && (
          <span>
            {name && <span className="muted">{name} · </span>}
            <button className="quiet" onClick={signOut}>
              Sign out
            </button>
          </span>
        )}
      </header>
      {token ? (
        <Courts token={token} onSignedOut={signOut} />
      ) : (
        <SignIn
          onDone={(t, n) => {
            saveToken(t);
            setName(n);
            setToken(t);
          }}
        />
      )}
    </main>
  );
}

// ---------------------------------------------------------------- sign in
function SignIn({ onDone }: { onDone(token: string, name: string): void }) {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [noPassword, setNoPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void devLoginOn().then(setNoPassword);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const clean = cleanPhone(phone);
    if (clean === null) return setError('A mobile number has 10 digits.');
    setBusy(true);
    setError(null);
    try {
      const r = await adminApi.login(clean, noPassword && !password ? '-' : password);
      onDone(r.access_token, r.name);
    } catch (err) {
      setError(
        err instanceof AdminError && (err.status === 401 || err.status === 429)
          ? err.status === 429
            ? err.message
            : 'Phone number or password is wrong.'
          : 'Could not sign in. Try again.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="admin-card" onSubmit={submit}>
      <h1>Sign in</h1>
      <p className="muted">For the people who run food courts.</p>
      <label>
        Mobile number
        <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="username" required autoFocus />
      </label>
      {noPassword ? (
        <p className="login-test-note" role="note">
          <strong>Local test mode:</strong> no password needed.
        </p>
      ) : (
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="primary" disabled={busy}>
        {busy ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------- food courts
type Sheeted = { kind: 'court' } | { kind: 'outlet'; court: AdminCourt };

function Courts({ token, onSignedOut }: { token: string; onSignedOut(): void }) {
  const [courts, setCourts] = useState<AdminCourt[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<Sheeted | null>(null);
  const [printing, setPrinting] = useState<string | null>(null);

  // Every call goes through here: a token that no longer works sends the admin to sign in.
  const run = useCallback(
    async (fn: () => Promise<{ courts: AdminCourt[] }>): Promise<boolean> => {
      try {
        setCourts((await fn()).courts);
        setError(null);
        return true;
      } catch (e) {
        if (e instanceof AdminError && e.status === 401) onSignedOut();
        else setError(e instanceof AdminError ? e.message : 'Could not reach the server.');
        return false;
      }
    },
    [onSignedOut],
  );

  useEffect(() => {
    void run(() => adminApi.courts(token));
  }, [run, token]);

  function print(id: string) {
    setPrinting(id); // only this court's QR is shown when printing
    window.setTimeout(() => {
      window.print();
      setPrinting(null);
    }, 50);
  }

  return (
    <>
      <div className="admin-head">
        <h1>Food courts</h1>
        <button className="primary" onClick={() => setSheet({ kind: 'court' })}>
          + New food court
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {courts === null ? (
        !error && <p className="muted" role="status">Loading…</p>
      ) : courts.length === 0 ? (
        <p className="muted">No food courts yet. Make the first one.</p>
      ) : (
        courts.map((c) => {
          const link = `${window.location.origin}${courtPath(c.slug)}`;
          return (
            <section key={c.id} className="admin-court" aria-label={c.name} data-printing={printing === c.id}>
              <div className="admin-court-head">
                <div className="fc-qr-card">
                  <Qr text={link} label={`QR code for ${c.name}`} />
                  <strong>{c.name}</strong>
                  <span className="muted">Scan to order</span>
                </div>
                <div>
                  <h2>{c.name}</h2>
                  <p className="muted">
                    {c.location ? `${c.location} · ` : ''}
                    {c.outlets.length} outlet{c.outlets.length === 1 ? '' : 's'}
                  </p>
                  <code className="admin-link">{link}</code>
                  <p>
                    <button className="quiet" onClick={() => print(c.id)}>
                      Print the QR
                    </button>
                  </p>
                </div>
              </div>
              <ul className="admin-outlets" aria-label={`Outlets of ${c.name}`}>
                {c.outlets.map((o) => (
                  <li key={o.id}>
                    <span>
                      <strong>{o.name}</strong>
                      <br />
                      <span className="muted">
                        Owner {o.owner_name} · {o.owner_phone}
                      </span>
                    </span>
                    <span className={`cx-tag ${o.accepting_orders ? 'open' : 'shut'}`}>
                      {o.accepting_orders ? 'Taking orders' : 'Closed'}
                    </span>
                    <button
                      className="quiet"
                      onClick={() => void run(() => adminApi.setAccepting(token, c.id, o.id, !o.accepting_orders))}
                    >
                      {o.accepting_orders ? 'Close' : 'Open'}
                    </button>
                    <button
                      className="quiet danger"
                      onClick={() => {
                        if (window.confirm(`Remove ${o.name} from ${c.name}? Its shop and orders are not deleted.`)) {
                          void run(() => adminApi.remove(token, c.id, o.id));
                        }
                      }}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
              <button onClick={() => setSheet({ kind: 'outlet', court: c })}>+ Add outlet</button>
            </section>
          );
        })
      )}

      <CustomerReset token={token} onSignedOut={onSignedOut} />

      {sheet?.kind === 'court' && (
        <NewCourt
          onClose={() => setSheet(null)}
          onSave={async (name, location) => {
            const ok = await run(() => adminApi.createCourt(token, name, location));
            if (ok) setSheet(null);
            return ok;
          }}
        />
      )}
      {sheet?.kind === 'outlet' && (
        <AddOutlet
          court={sheet.court}
          onClose={() => setSheet(null)}
          onNew={async (o) => {
            const ok = await run(() => adminApi.addOutlet(token, sheet.court.id, o));
            if (ok) setSheet(null);
            return ok;
          }}
          onAttach={async (phone) => {
            const ok = await run(() => adminApi.attach(token, sheet.court.id, phone));
            if (ok) setSheet(null);
            return ok;
          }}
          error={error}
        />
      )}
    </>
  );
}

/** A customer forgot their password: type their number, read the temporary one to them. */
function CustomerReset({ token, onSignedOut }: { token: string; onSignedOut(): void }) {
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ name: string; temporary_password: string } | null>(null);
  const clean = cleanPhone(phone);

  async function reset(e: FormEvent) {
    e.preventDefault();
    if (clean === null) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      setDone(await adminApi.resetCustomer(token, clean));
      setPhone('');
    } catch (err) {
      if (err instanceof AdminError && err.status === 401) onSignedOut();
      else setError(err instanceof AdminError ? err.message : 'Could not reach the server.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="admin-court" aria-label="Forgotten customer password">
      <h2>Forgotten customer password</h2>
      <form className="admin-form" onSubmit={reset}>
        <label>
          Customer's mobile number
          <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" />
        </label>
        <button className="primary" disabled={busy || clean === null}>
          Reset password
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {done && (
        <div role="status">
          <p className="muted">
            Temporary password for <strong>{done.name}</strong> (shown once):
          </p>
          <p className="admin-temp">{done.temporary_password}</p>
          <p className="muted">Tell them to log in with it; the app will ask them for a new one.</p>
        </div>
      )}
    </section>
  );
}

function NewCourt({ onClose, onSave }: { onClose(): void; onSave(name: string, location: string): Promise<boolean> }) {
  const [name, setName] = useState('');
  const [location, setLocation] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Sheet title="New food court" onClose={onClose}>
      <form
        className="admin-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          await onSave(name.trim(), location.trim());
          setBusy(false);
        }}
      >
        <label>
          Name customers will see
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Marina Food Court" autoFocus />
        </label>
        <label>
          Where it is <span className="muted">(customers pick by this)</span>
          <input value={location} onChange={(e) => setLocation(e.target.value)} maxLength={120} placeholder="Marina Beach, Chennai" />
        </label>
        <button className="primary" disabled={busy || name.trim().length < 2}>
          Create food court
        </button>
      </form>
    </Sheet>
  );
}

function AddOutlet({
  court,
  onClose,
  onNew,
  onAttach,
  error,
}: {
  court: AdminCourt;
  onClose(): void;
  onNew(o: { shop_name: string; owner_name: string; owner_phone: string; password: string | null; sample_menu: boolean }): Promise<boolean>;
  onAttach(phone: string): Promise<boolean>;
  error: string | null;
}) {
  const [shop, setShop] = useState('');
  const [owner, setOwner] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [sample, setSample] = useState(false);
  const [existing, setExisting] = useState('');
  const [busy, setBusy] = useState(false);
  const newPhone = cleanPhone(phone);
  const attachPhone = cleanPhone(existing);

  return (
    <Sheet title={`Add an outlet to ${court.name}`} label="Add an outlet" onClose={onClose}>
      <form
        className="admin-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (newPhone === null) return;
          setBusy(true);
          await onNew({
            shop_name: shop.trim(),
            owner_name: owner.trim() || 'Owner',
            owner_phone: newPhone,
            password: password || null,
            sample_menu: sample,
          });
          setBusy(false);
        }}
      >
        <h3>A new outlet</h3>
        <label>
          Outlet name
          <input value={shop} onChange={(e) => setShop(e.target.value)} maxLength={120} placeholder="Anna Biryani" />
        </label>
        <label>
          Owner&apos;s name
          <input value={owner} onChange={(e) => setOwner(e.target.value)} maxLength={120} />
        </label>
        <label>
          Owner&apos;s mobile number
          <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" />
        </label>
        {phone !== '' && newPhone === null && <p className="error">A mobile number has 10 digits.</p>}
        <label>
          Temporary password <span className="muted">(optional, 8+ characters)</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </label>
        <p className="muted">The owner chooses their own password the first time they sign in.</p>
        <label className="cx-check">
          <input type="checkbox" checked={sample} onChange={(e) => setSample(e.target.checked)} />
          Add a sample menu (for trying it out)
        </label>
        <button className="primary" disabled={busy || shop.trim().length < 2 || newPhone === null || (password !== '' && password.length < 8)}>
          Create outlet and add it
        </button>
      </form>

      <form
        className="admin-form admin-attach"
        onSubmit={async (e) => {
          e.preventDefault();
          if (attachPhone === null) return;
          setBusy(true);
          await onAttach(attachPhone);
          setBusy(false);
        }}
      >
        <h3>Or a shop that already exists</h3>
        <label>
          Owner&apos;s mobile number
          <input value={existing} onChange={(e) => setExisting(e.target.value)} inputMode="tel" />
        </label>
        <button disabled={busy || attachPhone === null}>Attach</button>
      </form>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  );
}

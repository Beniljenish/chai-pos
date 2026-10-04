import { useState, type FormEvent } from 'react';
import { HttpError, NetworkError } from '../lib/api';
import { useSession } from './session';

export function LoginScreen() {
  const { login } = useSession();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(phone, password);
    } catch (err) {
      if (err instanceof NetworkError) setError('No internet. Logging in needs a connection; billing does not.');
      else if (err instanceof HttpError && err.status === 401) setError('Phone number or password is wrong.');
      else if (err instanceof HttpError && err.status === 429 && typeof err.detail === 'string') setError(err.detail);
      else if (err instanceof HttpError && err.status === 422) setError('Enter a 10-digit mobile number.');
      else setError('Could not log in. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-hero">
        <ChaiCup />
        <h1>Taptallow</h1>
        <p className="login-tagline">Billing and stock for tea and juice shops</p>
        <ul className="login-points" aria-label="What it does">
          <li>Bills even when the internet drops</li>
          <li>GST worked out on every line</li>
          <li>Stock that matches the shelf</li>
        </ul>
      </section>
      <form className="login-card" onSubmit={submit}>
        <h2>Log in</h2>
        <p className="muted">Use the mobile number your shop owner set up for you.</p>
        <label>
          Mobile number
          <input
            inputMode="numeric"
            autoComplete="username"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>
          {busy ? 'Logging in…' : 'Log in'}
        </button>
      </form>
    </main>
  );
}

/** A glass of chai: the tea pours in, the steam rises, the glass floats.
 * Pure CSS (styles.css, "login"); still for anyone who asks for less motion. */
function ChaiCup() {
  return (
    <svg className="chai-cup" viewBox="0 0 160 160" width="148" height="148" aria-hidden="true">
      <defs>
        <clipPath id="cup-inside">
          <path d="M42 62h68l-7 62a10 10 0 0 1-10 9H59a10 10 0 0 1-10-9z" />
        </clipPath>
        <linearGradient id="tea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e9a35a" />
          <stop offset="1" stopColor="#b9672a" />
        </linearGradient>
      </defs>
      <g className="steam">
        <path d="M62 50c-6-8 6-12 0-22" />
        <path d="M78 46c-6-8 6-12 0-22" />
        <path d="M94 50c-6-8 6-12 0-22" />
      </g>
      <g className="cup-body">
        <ellipse className="saucer" cx="76" cy="140" rx="46" ry="7" />
        <g clipPath="url(#cup-inside)">
          <rect className="tea" x="40" y="62" width="74" height="74" fill="url(#tea)" />
          <path className="tea-wave" d="M30 70q10-5 20 0t20 0 20 0 20 0 20 0 20 0v10H30z" fill="#f4c189" />
        </g>
        <path className="glass" d="M42 62h68l-7 62a10 10 0 0 1-10 9H59a10 10 0 0 1-10-9z" />
        <path className="glass" d="M109 76h6a12 12 0 0 1 0 24h-9" />
      </g>
    </svg>
  );
}

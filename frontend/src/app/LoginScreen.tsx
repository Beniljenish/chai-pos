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
      else if (err instanceof HttpError && err.status === 422) setError('Enter a 10-digit mobile number.');
      else setError('Could not log in. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="centered">
      <form className="panel login" onSubmit={submit}>
        <img src="/icon-192.png" alt="" width={56} height={56} className="login-icon" />
        <h1>Chai POS</h1>
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

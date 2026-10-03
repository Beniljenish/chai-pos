/**
 * One-time tablet setup. Each tablet gets its own invoice series (C1, C2, ...),
 * so only the owner may set one up: two tablets sharing a series would print
 * duplicate invoice numbers.
 */
import { useEffect, useState } from 'react';
import { HttpError, NetworkError } from '../lib/api';
import type { Device } from '../lib/types';
import { api } from './apiClient';
import { useSession } from './session';

export function DeviceSetupScreen() {
  const { user, chooseDevice, logout } = useSession();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isOwner = user?.role === 'owner';

  useEffect(() => {
    if (!isOwner) return;
    api
      .get<Device[]>('/devices')
      .then(setDevices)
      .catch((e) => setError(e instanceof NetworkError ? 'Setting up a tablet needs internet.' : 'Could not load tablets.'));
  }, [isOwner]);

  if (!isOwner) {
    return (
      <main className="centered">
        <div className="panel">
          <h1>This tablet is not set up yet</h1>
          <p>Ask the owner to log in once on this tablet and set it up. After that, anyone can log in here.</p>
          <button onClick={logout}>Log out</button>
        </div>
      </main>
    );
  }

  async function register() {
    setBusy(true);
    setError(null);
    try {
      const dev = await api.post<Device>('/devices', { name: name.trim() || 'Counter' });
      await chooseDevice(dev);
    } catch (e) {
      setError(e instanceof HttpError ? 'Could not set up the tablet. Try again.' : 'Setting up a tablet needs internet.');
      setBusy(false);
    }
  }

  return (
    <main className="centered">
      <div className="panel setup">
        <h1>Set up this tablet</h1>
        <p>Give it a name staff will recognise. It gets its own invoice numbers.</p>
        <label>
          Tablet name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Front counter" />
        </label>
        <button className="primary" onClick={register} disabled={busy}>
          Set up as a new tablet
        </button>

        {devices && devices.length > 0 && (
          <details className="reuse">
            <summary>This tablet was set up before</summary>
            <p className="warn">
              Choose its old name only if this is the same tablet (for example after clearing the browser).
              Never pick a name another tablet is using: both would print the same invoice numbers.
            </p>
            <ul>
              {devices.filter((d) => d.is_active).map((d) => (
                <li key={d.id}>
                  <button onClick={() => chooseDevice(d)}>
                    {d.name} <span className="muted">({d.code})</span>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </div>
    </main>
  );
}

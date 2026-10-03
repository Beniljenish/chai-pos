/**
 * Owner: the people who log in. Each has their own phone number and password,
 * so bills, voids and counts show who did them.
 */
import { useCallback, useEffect, useState } from 'react';
import { firstPassword, formatPhone } from '../lib/staff';
import type { StaffMember } from '../lib/types';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { explainError } from './errors';
import { PasswordForm } from './PasswordForm';
import { Sheet } from './Sheet';
import { useSession } from './session';

type Editing = { kind: 'new' } | { kind: 'person'; person: StaffMember } | { kind: 'me' };

export function StaffScreen() {
  const { user } = useSession();
  const [staff, setStaff] = useState<StaffMember[] | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStaff(await api.get<StaffMember[]>('/users'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const active = (staff ?? []).filter((s) => s.is_active);
  const off = (staff ?? []).filter((s) => !s.is_active);

  const row = (s: StaffMember) => (
    <li key={s.id}>
      <button onClick={() => setEditing(s.id === user?.id ? { kind: 'me' } : { kind: 'person', person: s })}>
        <span className="sop-name">
          <strong>{s.name}</strong>
          <span className="muted"> · {s.role === 'owner' ? 'Owner' : 'Cashier'}</span>
          {s.id === user?.id && <span className="muted"> (you)</span>}
        </span>
        <span className="sop-lines num">{formatPhone(s.phone)}</span>
        {s.locked && <span className="flag bad">Locked: too many wrong passwords</span>}
        {!s.locked && s.must_change_password && s.is_active && (
          <span className="flag wait">Has not set their own password yet</span>
        )}
      </button>
    </li>
  );

  return (
    <section className="staff">
      <header className="manage-head">
        <h1>Staff</h1>
        <button className="primary" onClick={() => setEditing({ kind: 'new' })}>
          + Add staff
        </button>
      </header>
      <p className="muted">
        Everyone logs in with their own mobile number and password. Bills, voids and counts are recorded under the
        person who did them.
      </p>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {staff === null ? (
        !error && <Loading />
      ) : (
        <>
          <ul className="sop-list staff-list">{active.map(row)}</ul>
          {off.length > 0 && (
            <>
              <h2>Switched off</h2>
              <ul className="sop-list staff-list off">{off.map(row)}</ul>
            </>
          )}
        </>
      )}

      {editing?.kind === 'new' && (
        <AddStaff
          onClose={() => setEditing(null)}
          onAdded={() => {
            void load();
          }}
        />
      )}
      {editing?.kind === 'person' && (
        <PersonSheet
          person={editing.person}
          onClose={() => setEditing(null)}
          onChanged={(p) => {
            setEditing({ kind: 'person', person: p });
            void load();
          }}
        />
      )}
      {editing?.kind === 'me' && (
        <Sheet title="Your password" onClose={() => setEditing(null)}>
          <PasswordForm forced={false} onDone={() => setEditing(null)} />
          <p className="muted">Saving logs you out on your other phones and tablets.</p>
        </Sheet>
      )}
    </section>
  );
}

/** Shown once: the owner tells the person, who replaces it at first login. */
function FirstPassword({ name, phone, password }: { name: string; phone: string; password: string }) {
  return (
    <div className="first-password" role="status">
      <p>
        Tell {name} to log in with <strong className="num">{formatPhone(phone)}</strong> and this password:
      </p>
      <p className="big num" aria-label={`Password: ${password}`}>
        {password}
      </p>
      <p className="muted">
        It is shown only now. {name} will be asked to choose their own password straight away, so you will not
        know it after that.
      </p>
    </div>
  );
}

function AddStaff({ onClose, onAdded }: { onClose(): void; onAdded(): void }) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState<'cashier' | 'owner'>('cashier');
  const [password] = useState(() => firstPassword());
  const [done, setDone] = useState<StaffMember | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const p = await api.post<StaffMember>('/users', { name: name.trim(), phone, role, password });
      setDone(p);
      onAdded();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={done ? `${done.name} added` : 'Add staff'} onClose={onClose}>
      {done ? (
        <>
          <FirstPassword name={done.name} phone={done.phone} password={password} />
          <div className="sheet-actions">
            <button className="primary" onClick={onClose}>
              Done
            </button>
          </div>
        </>
      ) : (
        <>
          <label>
            Name
            <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Mobile number (they log in with it)
            <input inputMode="numeric" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          <fieldset className="opt-row" aria-label="Role">
            <legend>Role</legend>
            <label className="check">
              <input type="radio" name="role" checked={role === 'cashier'} onChange={() => setRole('cashier')} />
              Cashier
            </label>
            <label className="check">
              <input type="radio" name="role" checked={role === 'owner'} onChange={() => setRole('owner')} />
              Owner
            </label>
          </fieldset>
          {role === 'owner' && (
            <p className="warn">
              An owner sees every price and report, changes recipes and prices, voids bills and manages staff.
              Give this only to a partner you trust with the money.
            </p>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="sheet-actions">
            <button className="primary" disabled={busy || !name.trim() || !phone.trim()} onClick={() => void add()}>
              Add {role === 'owner' ? 'owner' : 'cashier'}
            </button>
            <button onClick={onClose}>Cancel</button>
          </div>
        </>
      )}
    </Sheet>
  );
}

function PersonSheet({
  person,
  onClose,
  onChanged,
}: {
  person: StaffMember;
  onClose(): void;
  onChanged(p: StaffMember): void;
}) {
  const [reset, setReset] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function patch(body: object, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.patch<StaffMember>(`/users/${person.id}`, body));
      after?.();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={person.name} onClose={onClose}>
      <p className="muted">
        {person.role === 'owner' ? 'Owner' : 'Cashier'} · {formatPhone(person.phone)}
        {!person.is_active && ' · switched off'}
      </p>
      {reset ? (
        <FirstPassword name={person.name} phone={person.phone} password={reset} />
      ) : (
        person.is_active && (
          <>
            <button
              disabled={busy}
              onClick={() => {
                const p = firstPassword();
                void patch({ password: p }, () => setReset(p));
              }}
            >
              {person.locked ? 'Unlock and reset password' : 'Reset password'}
            </button>
            <p className="muted">
              For a forgotten password or a lost phone. {person.name} is logged out everywhere and must choose a new
              password at the next login.
            </p>
          </>
        )
      )}
      {person.is_active ? (
        <>
          <button className="danger" disabled={busy} onClick={() => void patch({ is_active: false })}>
            Switch off {person.name}
          </button>
          <p className="muted">
            For someone who has left. They are logged out at once and cannot log in. Their bills and counts stay on
            record under their name.
          </p>
        </>
      ) : (
        <button disabled={busy} onClick={() => void patch({ is_active: true })}>
          Switch {person.name} back on
        </button>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  );
}

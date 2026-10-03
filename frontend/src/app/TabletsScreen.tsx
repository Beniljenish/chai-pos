/**
 * Owner: every tablet's health. Bills still waiting on it, bills the server
 * refused, and printed bills that never reached the server (lost).
 */
import { useCallback, useEffect, useState } from 'react';
import { ago } from '../lib/health';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { explainError } from './errors';
import { useSession } from './session';

interface Tablet {
  id: string;
  name: string;
  code: string;
  is_active: boolean;
  last_seen_at: string | null;
  reported_at: string | null;
  pending_bills: number;
  pending_ops: number;
  oldest_pending_at: string | null;
  stuck: boolean;
  rejected: number;
  persisted_storage: boolean | null;
  app_version: string | null;
  unseen: boolean;
  missing_count: number;
  missing: string[];
}

const time = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', timeStyle: 'short' }).format(
    new Date(iso),
  );

export function TabletsScreen() {
  const { device } = useSession();
  const [tablets, setTablets] = useState<Tablet[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setTablets(await api.get<Tablet[]>('/devices-health'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function setActive(t: Tablet, active: boolean) {
    setBusy(true);
    try {
      await api.patch(`/devices/${t.id}`, { is_active: active });
      await load();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const problems = (tablets ?? []).filter((t) => t.is_active && (t.missing_count || t.stuck || t.rejected)).length;

  return (
    <section className="tablets">
      <header className="manage-head">
        <h1>Tablets</h1>
        <button className="quiet" onClick={() => void load()}>
          Refresh
        </button>
      </header>
      <p className="muted">
        Each tablet reports what it still holds whenever it has internet. A bill printed on a tablet that never reached
        the server, and is no longer on the tablet, shows here as missing.
      </p>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {tablets === null && !error && <Loading />}
      {tablets && (
        <p className={problems ? 'warn' : 'ok'} role="status">
          {problems
            ? `${problems} tablet${problems === 1 ? ' needs' : 's need'} attention.`
            : 'Every bill printed has reached the server.'}
        </p>
      )}
      <ul className="tablet-list">
        {(tablets ?? []).map((t) => (
          <li key={t.id} className={t.is_active ? '' : 'off'}>
            <div className="shift-head">
              <strong>
                {t.name} <span className="muted">({t.code})</span>
                {t.id === device?.id && <span className="muted"> · this one</span>}
              </strong>
              {!t.is_active ? (
                <span className="flag wait">Switched off</span>
              ) : t.missing_count || t.stuck || t.rejected ? (
                <span className="flag bad">Check</span>
              ) : !t.last_seen_at ? (
                <span className="flag wait">Not used yet</span>
              ) : (
                <span className="flag ok">OK</span>
              )}
            </div>
            <p className="muted">
              {t.last_seen_at ? `Last seen ${ago(t.last_seen_at)}` : 'Never synced yet'}
              {t.app_version && ` · app ${t.app_version}`}
            </p>
            <ul className="tablet-facts">
              {t.missing_count > 0 && (
                <li className="bad-text">
                  <strong>
                    {t.missing_count} printed bill{t.missing_count === 1 ? '' : 's'} never reached the server:
                  </strong>{' '}
                  <span className="num">{t.missing.join(', ')}</span>
                  {t.missing_count > t.missing.length && ' …'}
                  <br />
                  <span className="muted">
                    Usually the tablet&apos;s browser data was cleared or the tablet was reset before these were sent.
                    Their sales are not in your reports; the paper receipts are the only record.
                  </span>
                </li>
              )}
              {t.pending_bills > 0 && (
                <li className={t.stuck ? 'bad-text' : ''}>
                  {t.pending_bills} bill{t.pending_bills === 1 ? '' : 's'} waiting to send
                  {t.oldest_pending_at && ` since ${time(t.oldest_pending_at)}`}
                  {t.stuck && ': check that tablet has internet and someone is logged in'}
                </li>
              )}
              {t.rejected > 0 && (
                <li className="bad-text">
                  {t.rejected} refused by the server: open that tablet&apos;s Today screen to see why
                </li>
              )}
              {t.unseen && t.is_active && t.last_seen_at && <li className="bad-text">Not seen for over a day</li>}
              {t.persisted_storage === false && (
                <li>
                  Its browser may clear saved bills when the tablet runs low on space. Add the app to the home screen
                  (browser menu → Install app) to protect them.
                </li>
              )}
            </ul>
            {t.is_active ? (
              t.id !== device?.id && (
                <button className="quiet" disabled={busy} onClick={() => void setActive(t, false)}>
                  Switch off (lost or no longer used)
                </button>
              )
            ) : (
              <button className="quiet" disabled={busy} onClick={() => void setActive(t, true)}>
                Switch back on
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

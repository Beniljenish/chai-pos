/**
 * Owner: every tablet's health. Bills still waiting on it, bills the server
 * refused, and printed bills that never reached the server (lost).
 */
import { Hint } from './Hint';
import { useCallback, useEffect, useState } from 'react';
import { ago, dayTime } from '../lib/health';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { explainError } from './errors';
import { useSession } from './session';
import { t } from '../lib/i18n';

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

  async function setActive(tb: Tablet, active: boolean) {
    setBusy(true);
    try {
      await api.patch(`/devices/${tb.id}`, { is_active: active });
      await load();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const problems = (tablets ?? []).filter((tb) => tb.is_active && (tb.missing_count || tb.stuck || tb.rejected)).length;

  return (
    <section className="tablets">
      <header className="manage-head">
        <h1>{t("Tablets")}</h1>
        <button className="quiet" onClick={() => void load()}>
          {t("Refresh")}
        </button>
      </header>
      <Hint>
        {t("Each tablet reports what it still holds whenever it has internet. A bill printed on a tablet that never reached the server, and is no longer on the tablet, shows here as missing.")}
      </Hint>
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
        {(tablets ?? []).map((tb) => (
          <li key={tb.id} className={tb.is_active ? '' : 'off'}>
            <div className="shift-head">
              <strong>
                {tb.name} <span className="muted">({tb.code})</span>
                {tb.id === device?.id && <span className="muted"> {t("· this one")}</span>}
              </strong>
              {!tb.is_active ? (
                <span className="flag wait">{t("Switched off")}</span>
              ) : tb.missing_count || tb.stuck || tb.rejected ? (
                <span className="flag bad">{t("Check")}</span>
              ) : !tb.last_seen_at ? (
                <span className="flag wait">{t("Not used yet")}</span>
              ) : (
                <span className="flag ok">{t("OK")}</span>
              )}
            </div>
            <p className="muted">
              {tb.last_seen_at ? `Last seen ${ago(tb.last_seen_at)}` : 'Never synced yet'}
              {tb.app_version && ` · app ${tb.app_version}`}
            </p>
            <ul className="tablet-facts">
              {tb.missing_count > 0 && (
                <li className="bad-text">
                  <strong>
                    {tb.missing_count} printed bill{tb.missing_count === 1 ? '' : 's'} never reached the server:
                  </strong>{' '}
                  <span className="num">{tb.missing.join(', ')}</span>
                  {tb.missing_count > tb.missing.length && ' …'}
                  <Hint>
                    Usually the tablet&apos;s browser data was cleared or the tablet was reset before these were sent.
                    Their sales are not in your reports; the paper receipts are the only record.
                  </Hint>
                </li>
              )}
              {tb.pending_bills > 0 && (
                <li className={tb.stuck ? 'bad-text' : ''}>
                  {tb.pending_bills} bill{tb.pending_bills === 1 ? '' : 's'} waiting to send
                  {tb.oldest_pending_at && ` since ${dayTime(tb.oldest_pending_at)}`}
                  {tb.stuck && ': check that tablet has internet and someone is logged in'}
                </li>
              )}
              {tb.rejected > 0 && (
                <li className="bad-text">
                  {tb.rejected} refused by the server: open that tablet&apos;s Today screen to see why
                </li>
              )}
              {tb.unseen && tb.is_active && tb.last_seen_at && <li className="bad-text">{t("Not seen for over a day")}</li>}
              {tb.persisted_storage === false && (
                <li>
                  {t("Its browser may clear saved bills when the tablet runs low on space. Add the app to the home screen (browser menu → Install app) to protect them.")}
                </li>
              )}
            </ul>
            {tb.is_active ? (
              tb.id !== device?.id && (
                <button className="quiet" disabled={busy} onClick={() => void setActive(tb, false)}>
                  {t("Switch off (lost or no longer used)")}
                </button>
              )
            ) : (
              <button className="quiet" disabled={busy} onClick={() => void setActive(tb, true)}>
                {t("Switch back on")}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

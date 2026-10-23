/**
 * Owner: what needs attention, worked out by the server from the day's records
 * (drawer, voids, discounts, waiting wastage, ingredient prices, recipe use).
 */
import { t } from '../lib/i18n';
import { Hint } from './Hint';
import { useCallback, useEffect, useState } from 'react';
import { groupAlerts, URGENCY_LABEL } from '../lib/alerts';
import type { AlertItem } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading, LoadError } from './Status';

const OPENS: Record<string, string> = {
  sales: 'Open Sales',
  dayend: 'Open Day end',
  margin: 'Open Margin',
  stock: 'Open Stock',
};

const time = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', timeStyle: 'short' }).format(new Date(iso));

export function AlertsScreen({ onOpen }: { onOpen: (section: string) => void }) {
  const [items, setItems] = useState<AlertItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems((await api.get<{ alerts: AlertItem[] }>('/reports/alerts')).alerts);
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="alerts">
      <header className="manage-head">
        <h1>Alerts</h1>
        <button className="quiet" onClick={() => void load()}>
          Refresh
        </button>
      </header>
      <Hint>What went wrong or changed, worked out from your records. Nothing here is a guess.</Hint>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {items === null ? (
        !error && <Loading />
      ) : items.length === 0 ? (
        <p className="alerts-clear">{t("Nothing needs you right now.")}</p>
      ) : (
        groupAlerts(items).map((g) => (
          <section key={g.label} aria-label={g.label}>
            <h2>{g.label}</h2>
            <ul className="alert-list">
              {g.items.map((a) => (
                <li key={a.id} className={`alert alert-${a.urgency}`}>
                  <span className="alert-dot" aria-hidden="true" />
                  <div>
                    <strong>{a.title}</strong>
                    <span className="alert-level">{URGENCY_LABEL[a.urgency]}</span>
                    <p>{a.detail}</p>
                    {OPENS[a.section] && (
                      <button className="quiet" onClick={() => onOpen(a.section)}>
                        {OPENS[a.section]}
                      </button>
                    )}
                  </div>
                  {a.at && <time dateTime={a.at}>{time(a.at)}</time>}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </section>
  );
}

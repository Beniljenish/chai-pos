/** Festivals and other special days, with what the same date brought last year (README, "9.21"). */
import { useCallback, useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading } from './Status';

interface Day {
  id: string;
  day: string;
  name: string;
  last_year_date: string;
  last_year_paise: number;
  last_year_bills: number;
  usual_weekday_paise: number | null;
}
interface Data {
  days: Day[];
  suggestions: { day: string; name: string }[];
}

export function SpecialDaysScreen() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.get<Data>('/special-days'));
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function add(d: string, n: string) {
    setBusy(true);
    setError(null);
    try {
      setData(await api.post<Data>('/special-days', { day: d, name: n }));
      setDay('');
      setName('');
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    setBusy(true);
    try {
      setData(await api.delete<Data>(`/special-days/${id}`));
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="special-days">
      <header className="manage-head">
        <h1>{t('Special days')}</h1>
      </header>
      <p className="muted">
        {t('Mark a festival or event. You see what the same date brought last year against that weekday’s usual, so you can prepare. Festivals that move each year (Diwali, Pongal, Eid) are yours to add.')}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form
        className="panel-inline"
        onSubmit={(e) => {
          e.preventDefault();
          void add(day, name);
        }}
      >
        <label>
          {t('Name')}
          <input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="Diwali" />
        </label>
        <label>
          {t('Date')}
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
        <button className="primary" disabled={busy || !day || !name.trim()}>
          {t('Add special day')}
        </button>
      </form>
      {!data && !error && <Loading />}
      {data && data.days.length === 0 && <p className="muted">{t('No special days coming up yet.')}</p>}
      {data?.days.map((d) => (
        <section key={d.id} className="panel-inline" aria-label={d.name}>
          <h2>
            {d.name} · {d.day}
          </h2>
          {d.last_year_bills === 0 ? (
            <p className="muted">{t('No sales were recorded on {date} last year.', { date: d.last_year_date })}</p>
          ) : (
            <p>
              {t('Last year that day')}: <strong className="num">{formatRupees(d.last_year_paise)}</strong>
              {d.usual_weekday_paise !== null && (
                <span className="muted">
                  {' '}
                  ({t('a usual day then: {amount}', { amount: formatRupees(d.usual_weekday_paise) })})
                </span>
              )}
            </p>
          )}
          <button className="quiet" disabled={busy} onClick={() => void remove(d.id)}>
            {t('Remove')}
          </button>
        </section>
      ))}
      {data && data.suggestions.length > 0 && (
        <>
          <h2>{t('Fixed-date days you may want')}</h2>
          <ul className="sop-list">
            {data.suggestions.slice(0, 6).map((s) => (
              <li key={`${s.day}${s.name}`}>
                <span>
                  {s.name} · {s.day}
                </span>
                <button disabled={busy} onClick={() => void add(s.day, s.name)}>
                  {t('Add')}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/**
 * Staff attendance (README, "9.21"). `ClockCard` is on the till's Today screen for whoever is
 * logged in; `AttendanceScreen` (Manage) is the owner's hours and pay sheet, with a CSV.
 */
import { useCallback, useEffect, useState } from 'react';
import { attendanceRows, hm, rateToPaise, type AttendanceEntry, type AttendanceReport } from '../lib/attendance';
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import { presets, toCsv } from '../lib/reports';
import { api } from './apiClient';
import { explainError } from './errors';
import { Sheet } from './Sheet';
import { Loading } from './Status';

const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
const clock = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso));

/** Clock in and out for the person logged in. Needs a connection (it is not a bill). */
export function ClockCard() {
  const [open, setOpen] = useState<AttendanceEntry | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get<{ open: AttendanceEntry | null }>('/attendance/me').then(
      (r) => setOpen(r.open),
      () => setOpen(undefined), // offline: the card simply is not shown
    );
  }, []);
  if (open === undefined) return null;
  async function tap() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ open: AttendanceEntry | null }>(open ? '/attendance/out' : '/attendance/in', {});
      setOpen(r.open);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel-inline clock-card" aria-label={t('Attendance')}>
      <span>
        {open ? t('Clocked in at {time}', { time: clock(open.clock_in_at) }) : t('Not clocked in')}
      </span>
      <button className={open ? 'quiet' : 'primary'} disabled={busy} onClick={() => void tap()}>
        {open ? t('Clock out') : t('Clock in')}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

const local = (iso: string) => {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export function AttendanceScreen() {
  const ranges = presets(today());
  const [range, setRange] = useState(ranges[1]);
  const [rep, setRep] = useState<AttendanceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fixing, setFixing] = useState<AttendanceEntry | null>(null);
  const [inAt, setInAt] = useState('');
  const [outAt, setOutAt] = useState('');
  const [rates, setRates] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRep(await api.get<AttendanceReport>(`/attendance?from=${range.from}&to=${range.to}`));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [range]);
  useEffect(() => {
    void load();
  }, [load]);

  async function saveRate(userId: string) {
    const paise = rateToPaise(rates[userId] ?? '');
    if (paise === null) return setError(t('Type the hourly rate in rupees, like 60 or 62.50.'));
    setBusy(true);
    try {
      await api.patch(`/users/${userId}`, { hourly_rate_paise: paise });
      setRates((r) => ({ ...r, [userId]: '' }));
      await load();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveFix() {
    if (!fixing) return;
    setBusy(true);
    try {
      await api.patch(`/attendance/${fixing.id}`, {
        clock_in_at: new Date(inAt).toISOString(),
        clock_out_at: outAt ? new Date(outAt).toISOString() : null,
      });
      setFixing(null);
      await load();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  function download() {
    if (!rep) return;
    const url = URL.createObjectURL(new Blob([toCsv(attendanceRows(rep))], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `attendance-${rep.from}-to-${rep.to}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <section className="attendance">
      <header className="manage-head">
        <h1>{t('Attendance')}</h1>
      </header>
      <div className="fc-ranges" role="group" aria-label={t('Dates')}>
        {ranges.map((r) => (
          <button key={r.label} className={r.label === range.label ? 'primary' : 'quiet'} onClick={() => setRange(r)}>
            {t(r.label)}
          </button>
        ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!rep && !error && <Loading />}
      {rep && rep.people.length === 0 && <p className="muted">{t('Nobody clocked in during these days.')}</p>}
      {rep?.people.map((p) => (
        <section key={p.user_id} className="panel-inline" aria-label={p.name}>
          <h2>
            {p.name}: <span className="num">{hm(p.minutes)}</span>
            {p.still_in && <span className="flag wait"> {t('still in')}</span>}
          </h2>
          <p>
            {p.pay_paise !== null ? (
              <>
                {t('Pay')}: <strong className="num">{formatRupees(p.pay_paise)}</strong>{' '}
                <span className="muted">
                  ({t('at {rate} an hour', { rate: formatRupees(p.rate_paise ?? 0) })})
                </span>
              </>
            ) : (
              <span className="muted">{t('No hourly rate set, so no pay is worked out.')}</span>
            )}
          </p>
          <label>
            {t('Hourly rate (₹)')}
            <input
              value={rates[p.user_id] ?? ''}
              inputMode="decimal"
              placeholder={p.rate_paise ? String(p.rate_paise / 100) : ''}
              onChange={(e) => setRates((r) => ({ ...r, [p.user_id]: e.target.value }))}
            />
          </label>
          <button disabled={busy || !(rates[p.user_id] ?? '')} onClick={() => void saveRate(p.user_id)}>
            {t('Save rate')}
          </button>
          <ul className="sop-list">
            {p.entries.map((e) => (
              <li key={e.id}>
                <span>
                  {e.date} · {clock(e.clock_in_at)} → {e.clock_out_at ? clock(e.clock_out_at) : t('still in')}
                  {e.edited && <span className="muted"> · {t('corrected')}</span>}
                  {e.too_long && <span className="flag bad"> {t('very long: forgot to clock out?')}</span>}
                </span>
                <span className="num">{e.minutes === null ? '' : hm(e.minutes)}</span>
                <button
                  className="quiet"
                  onClick={() => {
                    setFixing(e);
                    setInAt(local(e.clock_in_at));
                    setOutAt(e.clock_out_at ? local(e.clock_out_at) : '');
                  }}
                >
                  {t('Correct')}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {rep && rep.people.length > 0 && <button onClick={download}>{t('Download (CSV)')}</button>}
      {fixing && (
        <Sheet title={t('Correct this entry')} onClose={() => setFixing(null)}>
          <label>
            {t('In')}
            <input type="datetime-local" value={inAt} onChange={(e) => setInAt(e.target.value)} />
          </label>
          <label>
            {t('Out')}
            <input type="datetime-local" value={outAt} onChange={(e) => setOutAt(e.target.value)} />
          </label>
          <p className="muted">{t('Your correction is written in the change log.')}</p>
          <div className="sheet-actions">
            <button className="primary" disabled={busy || !inAt} onClick={() => void saveFix()}>
              {t('Save')}
            </button>
            <button onClick={() => setFixing(null)}>{t('Cancel')}</button>
          </div>
        </Sheet>
      )}
    </section>
  );
}

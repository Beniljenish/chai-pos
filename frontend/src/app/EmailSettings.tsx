/** Where the owner's reports go, which ones, and a button to prove it works. */
import { useEffect, useState } from 'react';
import { api } from './apiClient';
import { explainError } from './errors';

interface Settings {
  report_email: string | null;
  email_each_bill: boolean;
  email_day_end: boolean;
  email_daily: boolean;
  email_weekly: boolean;
}

const SWITCHES: { key: keyof Omit<Settings, 'report_email'>; label: string; hint: string }[] = [
  { key: 'email_daily', label: 'Daily sales summary', hint: 'Every morning at 7: yesterday by cash / UPI / card, GST, top items.' },
  { key: 'email_day_end', label: 'Day-end report', hint: 'When you close a day: what is missing, in units and ₹, and wastage.' },
  { key: 'email_weekly', label: 'Weekly data export', hint: 'Mondays: all bills, items, stock movements and wastage as Excel-ready files.' },
  {
    key: 'email_each_bill',
    label: 'Every bill',
    hint: 'One email per sale. A busy shop sends hundreds a day; the free email plan allows 100 a day.',
  },
];

export function EmailSettings() {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<Settings>('/shop').then(
      (s) => {
        setSaved(s);
        setDraft(s);
      },
      (e) => setMessage({ ok: false, text: explainError(e) }),
    );
  }, []);

  if (!draft || !saved) return null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      const s = await api.patch<Settings>('/shop', { ...draft, report_email: draft!.report_email ?? '' });
      setSaved(s);
      setDraft(s);
      setMessage({ ok: true, text: 'Saved.' });
    } catch (e) {
      setMessage({ ok: false, text: explainError(e) });
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.post<{ status: string; to?: string; detail?: string }>('/shop/test-email', {});
      setMessage(
        r.status === 'sent'
          ? { ok: true, text: `Test email sent to ${r.to}. Check the inbox (and spam).` }
          : { ok: false, text: r.detail ?? 'The email could not be sent.' },
      );
    } catch (e) {
      setMessage({ ok: false, text: explainError(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="email-settings" aria-labelledby="email-title">
      <h2 id="email-title">Reports by email</h2>
      <div className="panel-inline">
        <label>
          Send reports to
          <input
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="owner@example.com"
            value={draft.report_email ?? ''}
            onChange={(e) => setDraft({ ...draft, report_email: e.target.value })}
          />
        </label>
        {SWITCHES.map((s) => (
          <label key={s.key} className="check email-switch">
            <input
              type="checkbox"
              checked={draft[s.key]}
              onChange={(e) => setDraft({ ...draft, [s.key]: e.target.checked })}
            />
            <span>
              {s.label}
              <br />
              <span className="muted">{s.hint}</span>
            </span>
          </label>
        ))}
        <div className="sheet-actions">
          <button className="primary" disabled={!dirty || busy} onClick={() => void save()}>
            Save email settings
          </button>
          <button disabled={dirty || busy || !saved.report_email} onClick={() => void test()}>
            Send test email
          </button>
        </div>
        {dirty && <p className="muted">Save first, then send a test.</p>}
        {message && (
          <p className={message.ok ? 'ok' : 'error'} role={message.ok ? 'status' : 'alert'}>
            {message.text}
          </p>
        )}
      </div>
    </section>
  );
}

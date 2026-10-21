/** One bill's history: who rang it, discounts, cancelled items, payment, void (README, "9.16"). */
import { useState } from 'react';
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import type { Fact } from '../lib/watch';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading } from './Status';

export const clock = (iso: string): string =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit', day: 'numeric', month: 'short' }).format(
    new Date(iso),
  );

export function FactList({ facts }: { facts: Fact[] }) {
  return (
    <ol className="trail" aria-label={t('Bill history')}>
      {facts.map((f, i) => (
        <li key={i} className={`trail-${f.kind}`}>
          <time dateTime={f.at}>{clock(f.at)}</time>
          <div>
            <strong>{t(f.title)}</strong>
            {f.amount_paise !== null && <span className="num"> {formatRupees(f.amount_paise)}</span>}
            {f.detail && <p className="muted">{f.detail}</p>}
            {f.by && <small className="muted">{f.by}</small>}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** A button that opens the bill's history in place. Owner only (the server says no to others). */
export function TrailPanel({ billId }: { billId: string }) {
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function show() {
    setBusy(true);
    setError(null);
    try {
      setFacts((await api.get<{ facts: Fact[] }>(`/bills/${billId}/trail`)).facts);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  if (facts === null) {
    return (
      <div className="trail-box">
        <button className="quiet" onClick={() => void show()} disabled={busy}>
          {t('Show bill history')}
        </button>
        {busy && <Loading />}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="trail-box">
      <FactList facts={facts} />
      <p className="muted">{t('A bill cannot be edited: the database refuses. Mistakes are voided and billed again.')}</p>
    </div>
  );
}

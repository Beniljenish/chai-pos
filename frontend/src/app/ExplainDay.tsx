/**
 * "Why?" under the variance (README, "9.16"): the day's facts from the records (voids, discounts,
 * cancelled items, wastage), and a few plain sentences about them. Every reason points at a fact
 * the server listed; the AI cannot add a number of its own.
 */
import { useState } from 'react';
import type { DayExplain } from '../lib/aiTypes';
import { formatRupees } from '../lib/gst';
import { getLang, t } from '../lib/i18n';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading } from './Status';
import { useAiStatus } from './useAi';

export function ExplainDay({ day }: { day: string }) {
  const [used, setUsed] = useState(0);
  const status = useAiStatus(used);
  const [data, setData] = useState<DayExplain | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function explain() {
    setBusy(true);
    setError(null);
    try {
      setData(await api.post<DayExplain>(`/ai/explain-day?date=${day}&lang=${getLang()}`, {}));
      setUsed((n) => n + 1);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  if (status && !status.on) return null; // not switched on: the variance list above says it all
  const reasonFor = (id: string) => data?.reasons.find((r) => r.fact_id === id)?.text;
  return (
    <section className="explain" aria-label={t('Why is the stock off?')}>
      <button className="quiet" disabled={busy || !status?.on} onClick={() => void explain()}>
        ✨ {t('Why? Explain this day')}
      </button>
      {busy && <Loading />}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data && data.facts.length === 0 && <p className="muted">{t('Nothing unusual was recorded this day.')}</p>}
      {data && data.summary && <p className="explain-summary">{data.summary}</p>}
      {data && data.facts.length > 0 && (
        <ul className="explain-facts">
          {data.facts.map((f) => (
            <li key={f.id} className={`fact-${f.kind}`}>
              <span>{f.text}</span>
              {reasonFor(f.id) && <em>{reasonFor(f.id)}</em>}
              {f.amount_paise !== undefined && f.kind !== 'stock' && <small className="num muted">{formatRupees(f.amount_paise)}</small>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

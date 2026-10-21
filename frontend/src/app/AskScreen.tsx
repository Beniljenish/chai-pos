/**
 * Owner: ask the shop a question in Tamil or English (README, "9.16"). The answer is built from
 * fixed reports on your own records; the AI only chooses the report and phrases the result, and it
 * cannot change anything.
 */
import { useState, type FormEvent } from 'react';
import type { AskAnswer } from '../lib/aiTypes';
import { getLang, t, useLang } from '../lib/i18n';
import { api } from './apiClient';
import { explainError } from './errors';
import { Mic } from './Mic';
import { useAiStatus } from './useAi';

const EXAMPLES = ['How much did I sell today?', 'What are my best sellers this week?', 'How much was wasted this week?', 'What is running low?'];

interface Turn {
  question: string;
  answer: AskAnswer;
}

export function AskScreen() {
  useLang();
  const [used, setUsed] = useState(0);
  const status = useAiStatus(used);
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(q: string) {
    if (q.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const answer = await api.post<AskAnswer>('/ai/ask', { question: q.trim(), lang: getLang() });
      setTurns((all) => [{ question: q.trim(), answer }, ...all]);
      setQuestion('');
      setUsed((n) => n + 1);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  return (
    <section className="ask">
      <header className="manage-head">
        <h1>{t('Ask your shop')}</h1>
      </header>
      <p className="muted">{t('Ask in Tamil or English. Answers come from your own records. It only reads: it cannot change anything.')}</p>
      {status && !status.on && <p className="cx-note">{t('The AI helpers are not switched on yet.')}</p>}
      {status?.pretend && <p className="cx-note">{t('Pretend mode: simple rules stand in for the AI. Real Tamil needs the real AI.')}</p>}
      <form className="ask-form" onSubmit={submit}>
        <input
          value={question}
          maxLength={300}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('Type your question')}
          aria-label={t('Your question')}
        />
        <button className="primary" disabled={busy || !status?.on || question.trim().length < 2}>
          {busy ? t('Thinking…') : t('Ask')}
        </button>
      </form>
      <Mic onText={(spoken) => setQuestion(spoken)} label={t('Speak your question')} />
      <div className="chips" role="group" aria-label={t('Examples')}>
        {EXAMPLES.map((ex) => (
          <button key={ex} className="chip" disabled={busy || !status?.on} onClick={() => void ask(t(ex))}>
            {t(ex)}
          </button>
        ))}
      </div>
      {status?.on && (
        <small className="muted">{t('{used} of {limit} AI questions used today', { used: status.used_today, limit: status.daily_limit })}</small>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <ul className="ask-turns">
        {turns.map((turn, i) => (
          <li key={i}>
            <p className="ask-q">{turn.question}</p>
            <p className="ask-a">{turn.answer.answer}</p>
            {turn.answer.lines.length > 0 && (
              <details>
                <summary>{t('From your records')}</summary>
                <ul>
                  {turn.answer.lines.map((l) => (
                    <li key={l}>{l}</li>
                  ))}
                </ul>
                <small className="muted">
                  {turn.answer.from === turn.answer.to ? turn.answer.from : `${turn.answer.from} → ${turn.answer.to}`}
                </small>
              </details>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Owner: messages to customers (README, "Phase 8b"). Receipt links and "your
 * order is ready", only for customers who agreed. Numbers are shown masked.
 * Without an Inkbox key on the server, messages are written here and not sent.
 */
import { useCallback, useEffect, useState } from 'react';
import { dayTime } from '../lib/health';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading, LoadError } from './Status';

interface OutboxMessage {
  id: string;
  kind: 'receipt' | 'ready';
  to: string;
  text: string;
  status: 'pending' | 'sent' | 'logged' | 'failed';
  attempts: number;
  last_error: string;
  created_at: string;
}

const STATUS: Record<OutboxMessage['status'], string> = {
  pending: 'Waiting to send',
  sent: 'Sent',
  logged: 'Not sent (no provider)',
  failed: 'Failed',
};
const KIND: Record<OutboxMessage['kind'], string> = { receipt: 'Receipt', ready: 'Order ready' };


export function MessagesScreen() {
  const [data, setData] = useState<{ provider: 'inkbox' | 'log'; messages: OutboxMessage[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.get('/messages'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function retry() {
    setBusy(true);
    try {
      await api.post('/messages/retry', {});
      await load();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const waiting = data?.messages.filter((m) => m.status === 'pending').length ?? 0;
  return (
    <section className="messages-screen">
      <header className="manage-head">
        <h1>Messages</h1>
        {waiting > 0 && (
          <button className="quiet" onClick={() => void retry()} disabled={busy}>
            Send {waiting} waiting now
          </button>
        )}
      </header>
      <p className="muted">
        Receipts and &quot;order ready&quot; go by iMessage to customers who agreed when their number was taken (Tables →
        Customer). Only the last four digits are shown here.
      </p>
      {data?.provider === 'log' && (
        <p className="warn">
          Sending is not set up yet: messages are written here but not sent. Adding the Inkbox key on the server turns
          sending on.
        </p>
      )}
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {data === null && !error && <Loading />}
      {data && data.messages.length === 0 && (
        <div className="empty-card">
          <p>
            <strong>No messages yet.</strong> They appear when a takeaway is marked ready in the kitchen, or a table or
            takeaway is settled, for a customer who agreed to messages.
          </p>
        </div>
      )}
      {data && data.messages.length > 0 && (
        <ul className="void-list message-list">
          {data.messages.map((m) => (
            <li key={m.id} className={m.status === 'failed' ? 'after-bill' : ''}>
              <strong>{KIND[m.kind]}</strong> · <span className="num">{m.to}</span> · {dayTime(m.created_at)} ·{' '}
              <span className={m.status === 'failed' ? 'error' : m.status === 'sent' ? 'ok' : ''}>{STATUS[m.status]}</span>
              <br />
              <span className="muted">{m.text}</span>
              {m.last_error && m.status !== 'sent' && (
                <>
                  <br />
                  <span className="muted">
                    {m.last_error} (tried {m.attempts}×)
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

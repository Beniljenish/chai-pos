/**
 * Customers and their khata (README, "Phase 6"). Staff find a customer, see
 * their visits and take a repayment at the counter (needs internet: only the
 * server knows what is owed). The owner sees everyone who owes under Manage.
 */
import { useCallback, useEffect, useState } from 'react';
import { uuidv7 } from '../lib/billing';
import { formatRupees } from '../lib/gst';
import { dayTime } from '../lib/health';
import { api } from './apiClient';
import { explainError } from './errors';
import { useSession } from './session';
import { Sheet } from './Sheet';
import { Loading, LoadError } from './Status';

interface CustomerRow {
  id: string;
  name: string;
  phone: string;
  outstanding_paise: number;
}

interface CustomerDetailData extends CustomerRow {
  visits: { bill_id: string; invoice_no: string; sold_at: string; total_paise: number; credit_paise: number; status: string }[];
  repayments: { id: string; amount_paise: number; mode: string; at: string; by_name: string; note: string }[];
}

const MODES = [
  { mode: 'cash', label: 'Cash' },
  { mode: 'upi', label: 'UPI' },
  { mode: 'card', label: 'Card' },
] as const;

/** Today → Customers: find someone by number or name. */
export function CustomersSheet({ onClose }: { onClose(): void }) {
  const [q, setQ] = useState('');
  const [found, setFound] = useState<CustomerRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    if (q.trim().length < 2) return;
    let live = true;
    const t = setTimeout(() => {
      api.get<{ customers: CustomerRow[] }>(`/customers?q=${encodeURIComponent(q.trim())}`).then(
        (r) => live && (setFound(r.customers), setError(null)),
        (e) => live && setError(explainError(e)),
      );
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [q]);

  if (open) return <CustomerDetail id={open} onClose={onClose} onBack={() => setOpen(null)} />;
  return (
    <Sheet title="Customers" onClose={onClose}>
      <label>
        Phone or name
        <input value={q} autoFocus maxLength={40} onChange={(e) => setQ(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      {q.trim().length >= 2 && found?.length === 0 && <p className="muted">No customer found. Customers are added on a bill.</p>}
      <ul className="sop-list">
        {(found ?? []).map((c) => (
          <li key={c.id}>
            <button onClick={() => setOpen(c.id)}>
              <strong>{c.name || c.phone}</strong> <span className="muted num">{c.phone}</span>
              {c.outstanding_paise > 0 && <span className="num"> · owes {formatRupees(c.outstanding_paise)}</span>}
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}

/** One customer: visits, khata, and a repayment. */
export function CustomerDetail({ id, onClose, onBack }: { id: string; onClose(): void; onBack?(): void }) {
  const { shift } = useSession();
  const [c, setC] = useState<CustomerDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState('');
  const [mode, setMode] = useState<'cash' | 'upi' | 'card'>('cash');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [payId, setPayId] = useState(() => uuidv7());

  const load = useCallback(async () => {
    try {
      const d = await api.get<CustomerDetailData>(`/customers/${id}`);
      setC(d);
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);

  const paise = Math.round(Number(amount || '0') * 100);
  async function repay() {
    setBusy(true);
    setError(null);
    try {
      // The id is made once per repayment: a retry after a timeout records it once.
      await api.post(`/customers/${id}/repayments`, {
        id: payId,
        amount_paise: paise,
        mode,
        ...(mode === 'cash' && shift ? { shift_id: shift.id } : {}),
      });
      setDone(`Received ${formatRupees(paise)} by ${MODES.find((m) => m.mode === mode)?.label}.`);
      setAmount('');
      setPayId(uuidv7());
      await load();
    } catch (e) {
      setError(explainError(e) === 'more_than_owed' ? 'That is more than they owe.' : explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet title={c ? c.name || c.phone : 'Customer'} onClose={onClose}>
      {onBack && (
        <button className="quiet" onClick={onBack}>
          ← All customers
        </button>
      )}
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {!c && !error && <Loading />}
      {c && (
        <>
          <p className="muted num">{c.phone}</p>
          <p className="khata-owed">
            {c.outstanding_paise > 0 ? (
              <>
                Owes <strong className="num">{formatRupees(c.outstanding_paise)}</strong>
              </>
            ) : (
              'Owes nothing'
            )}
          </p>
          {done && (
            <p className="ok" role="status">
              {done}
            </p>
          )}
          {c.outstanding_paise > 0 && (
            <fieldset className="repay">
              <legend>Take a repayment</legend>
              <label>
                Amount (₹)
                <input
                  inputMode="decimal"
                  value={amount}
                  placeholder={String(c.outstanding_paise / 100)}
                  onChange={(e) => /^\d{0,6}(\.\d{0,2})?$/.test(e.target.value) && setAmount(e.target.value)}
                />
              </label>
              <div className="chips" role="group" aria-label="Paid by">
                {MODES.map((m) => (
                  <button key={m.mode} className="chip" aria-pressed={mode === m.mode} onClick={() => setMode(m.mode)}>
                    {m.label}
                  </button>
                ))}
              </div>
              <button className="primary" disabled={busy || paise <= 0 || paise > c.outstanding_paise} onClick={() => void repay()}>
                Receive {paise > 0 ? formatRupees(paise) : ''}
              </button>
            </fieldset>
          )}
          <h3>Visits</h3>
          {c.visits.length === 0 && <p className="muted">No bills yet.</p>}
          <ul className="void-list neutral-list">
            {c.visits.map((v) => (
              <li key={v.bill_id}>
                <span className="num">{v.invoice_no}</span> · {dayTime(v.sold_at)} · {formatRupees(v.total_paise)}
                {v.credit_paise > 0 && <span className="num"> · {formatRupees(v.credit_paise)} on credit</span>}
                {v.status === 'void' && <strong className="error"> · voided</strong>}
              </li>
            ))}
          </ul>
          {c.repayments.length > 0 && (
            <>
              <h3>Repayments</h3>
              <ul className="void-list neutral-list">
                {c.repayments.map((r) => (
                  <li key={r.id}>
                    {formatRupees(r.amount_paise)} · {r.mode.toUpperCase()} · {dayTime(r.at)} · {r.by_name}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Sheet>
  );
}

/** Owner, Manage → Khata: everyone who owes, biggest first. */
export function KhataScreen() {
  const [data, setData] = useState<{ customers: CustomerRow[]; total_paise: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await api.get('/reports/khata'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section>
      <header className="manage-head">
        <h1>Khata</h1>
      </header>
      <p className="muted">Bills on credit, less repayments. A voided credit bill is no longer owed.</p>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {data === null && !error && <Loading />}
      {data && (
        <>
          <p>
            Owed to the shop: <strong className="num">{formatRupees(data.total_paise)}</strong>
          </p>
          {data.customers.length === 0 ? (
            <div className="empty-card">
              <p>
                <strong>Nobody owes anything.</strong> Bills put on credit at the till (Credit) appear here.
              </p>
            </div>
          ) : (
            <ul className="sop-list khata-list">
              {data.customers.map((c) => (
                <li key={c.id}>
                  <button onClick={() => setOpen(c.id)}>
                    <strong>{c.name || c.phone}</strong> <span className="muted num">{c.phone}</span>
                    <span className="num"> · {formatRupees(c.outstanding_paise)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {open && (
        <CustomerDetail
          id={open}
          onClose={() => {
            setOpen(null);
            void load();
          }}
        />
      )}
    </section>
  );
}

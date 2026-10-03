/**
 * Owner: one day's sales from the server (all tablets), and voiding a bill.
 * Totals are the printed invoices; voided bills are left out and listed below.
 */
import { useCallback, useEffect, useState } from 'react';
import { businessDate } from '../lib/billing';
import { formatRate, formatRupees } from '../lib/gst';
import { formatPriceDelta } from '../lib/options';
import {
  PAYMENT_LABELS,
  VOID_REASONS,
  dayLabel,
  hourBars,
  hourLabel,
  shiftDay,
  voidReasonLabel,
  type VoidReason,
} from '../lib/sales';
import type { SalesReport, ServerBill } from '../lib/types';
import { api } from './apiClient';

const FLAG_LABELS: Record<string, string> = {
  discount_over_limit: 'discount over the cashier limit',
  discount_without_reason: 'discount with no reason',
  payment_parts_mismatch: 'payment parts do not add up to the bill',
  credit_without_customer: 'on credit with no customer',
};
import { Loading, LoadError } from './Status';
import { Sheet } from './Sheet';
import { ServiceReport } from './ServiceReport';
import { CashDrawer } from './CashDrawer';
import { explainError } from './errors';
import { useSession } from './session';

const time = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', timeStyle: 'short' }).format(new Date(iso));

export function SalesScreen() {
  const { catalogue } = useSession();
  const [today] = useState(() => businessDate(new Date()));
  const [day, setDayState] = useState(today);
  const [report, setReport] = useState<SalesReport | null>(null);
  const [bills, setBills] = useState<ServerBill[] | null>(null);
  const [open, setOpen] = useState<ServerBill | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, b] = await Promise.all([
        api.get<SalesReport>(`/reports/sales?business_date=${day}`),
        api.get<ServerBill[]>(`/bills?business_date=${day}`),
      ]);
      setReport(r);
      setBills(b);
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [day]);

  useEffect(() => {
    void load();
  }, [load]);

  function setDay(next: (d: string) => string) {
    setReport(null); // never show one day's numbers under another day's name
    setBills(null);
    setDayState(next);
  }

  const regular = catalogue?.shop.gst_type === 'regular';
  const closed = report?.day_status === 'approved';

  return (
    <section className="sales">
      <header className="manage-head">
        <h1>Sales</h1>
        <div className="day-nav" role="group" aria-label="Which day">
          <button aria-label="Previous day" onClick={() => setDay((d) => shiftDay(d, -1))}>
            ‹
          </button>
          <span className="day-now">{dayLabel(day, today)}</span>
          <button aria-label="Next day" disabled={day >= today} onClick={() => setDay((d) => shiftDay(d, 1))}>
            ›
          </button>
        </div>
      </header>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {!report ? (
        !error && <Loading />
      ) : (
        <>
          <div className="sales-total">
            <p className="big num">{formatRupees(report.total_paise)}</p>
            <p className="muted">
              {report.bills} bill{report.bills === 1 ? '' : 's'}
              {report.voids.length > 0 &&
                ` · ${report.voids.length} voided (${formatRupees(report.voids.reduce((a, v) => a + v.total_paise, 0))}, not included)`}
            </p>
          </div>

          {report.by_mode.length > 0 && (
            <ul className="mode-split">
              {report.by_mode.map((m) => (
                <li key={m.mode}>
                  <span>{PAYMENT_LABELS[m.mode] ?? m.mode}</span>
                  <strong className="num">{formatRupees(m.total_paise)}</strong>
                  <span className="muted">
                    {m.bills} bill{m.bills === 1 ? '' : 's'}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {report.mismatches.length > 0 && (
            <div className="panel-inline warn-box" role="note">
              <strong>
                {report.mismatches.length} bill{report.mismatches.length === 1 ? '' : 's'} where the tablet&apos;s
                total differs from the server&apos;s
              </strong>
              <ul>
                {report.mismatches.map((m) => (
                  <li key={m.bill_id} className="num">
                    {m.invoice_no}: printed {formatRupees(m.total_paise)}, server {formatRupees(m.server_total_paise)}
                  </li>
                ))}
              </ul>
              <p className="muted">They count at the printed amount (that is what the customer paid).</p>
            </div>
          )}

          {((report.discounts ?? []).length > 0 || Boolean(report.credit_given_paise) || Boolean(report.repaid_paise)) && (
            <section aria-label="Discounts and credit">
              <h2>Discounts and credit</h2>
              {(report.discounts ?? []).length > 0 && (
                <>
                  <p>
                    Discounts: <strong className="num">{formatRupees(report.discount_paise ?? 0)}</strong> on{' '}
                    {(report.discounts ?? []).length} bill{(report.discounts ?? []).length === 1 ? '' : 's'}
                  </p>
                  <ul className="void-list neutral-list">
                    {(report.discounts ?? []).map((d) => (
                      <li key={d.bill_id} className={d.over_limit ? 'after-bill' : ''}>
                        <span className="num">{d.invoice_no}</span> · −{formatRupees(d.discount_paise)} ·{' '}
                        {d.reason || 'no reason'} · {d.by_name}
                        {d.over_limit && <strong className="error"> · over the cashier limit</strong>}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {(Boolean(report.credit_given_paise) || Boolean(report.repaid_paise)) && (
                <p>
                  Khata: <strong className="num">{formatRupees(report.credit_given_paise ?? 0)}</strong> given on credit,{' '}
                  <strong className="num">{formatRupees(report.repaid_paise ?? 0)}</strong> repaid.
                </p>
              )}
            </section>
          )}
          {(report.flagged ?? []).some((f) => f.flags.some((x) => x !== 'discount_over_limit')) && (
            <div className="panel-inline warn-box" role="note">
              <strong>Bills to look at</strong>
              <ul>
                {(report.flagged ?? []).map((f) => (
                  <li key={f.bill_id} className="num">
                    {f.invoice_no}: {f.flags.map((x) => FLAG_LABELS[x] ?? x).join(', ')}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Reloads when a void changes the day's cash. */}
          <CashDrawer day={day} refreshKey={report.voids.length} />

          {report.items.length > 0 && (
            <>
              <h2>Items</h2>
              <table className="sales-table">
                <thead>
                  <tr>
                    <th scope="col">Item</th>
                    <th scope="col" className="num">
                      Qty
                    </th>
                    <th scope="col" className="num">
                      Sales
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report.items.map((i) => (
                    <tr key={i.name}>
                      <th scope="row">{i.name}</th>
                      <td className="num">{i.qty}</td>
                      <td className="num">{formatRupees(i.total_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {report.by_hour.length > 0 && (
            <>
              <h2>By hour</h2>
              <ul className="hour-bars">
                {hourBars(report.by_hour).map((h) => (
                  <li key={h.hour}>
                    <span className="hour">{hourLabel(h.hour)}</span>
                    <span className="bar" aria-hidden="true">
                      <span style={{ width: `${h.pct}%` }} />
                    </span>
                    <span className="num">{h.total_paise ? formatRupees(h.total_paise) : '–'}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {report.by_cashier.length > 1 && (
            <>
              <h2>By staff</h2>
              <ul className="mode-split">
                {report.by_cashier.map((c) => (
                  <li key={c.name}>
                    <span>{c.name}</span>
                    <strong className="num">{formatRupees(c.total_paise)}</strong>
                    <span className="muted">{c.bills} bills</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {regular && report.gst_by_rate.length > 0 && (
            <>
              <h2>GST collected</h2>
              <table className="sales-table">
                <thead>
                  <tr>
                    <th scope="col">Rate</th>
                    <th scope="col" className="num">
                      Taxable
                    </th>
                    <th scope="col" className="num">
                      CGST
                    </th>
                    <th scope="col" className="num">
                      SGST
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report.gst_by_rate.map((g) => (
                    <tr key={g.rate_bp}>
                      <th scope="row">{formatRate(g.rate_bp)}</th>
                      <td className="num">{formatRupees(g.taxable_paise)}</td>
                      <td className="num">{formatRupees(g.cgst_paise)}</td>
                      <td className="num">{formatRupees(g.sgst_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <ServiceReport day={day} />

          {report.voids.length > 0 && (
            <>
              <h2>Voided</h2>
              <ul className="void-list">
                {report.voids.map((v) => (
                  <li key={v.bill_id}>
                    <span className="num">{v.invoice_no}</span> <span className="num">{formatRupees(v.total_paise)}</span>
                    <br />
                    <span className="muted">
                      {voidReasonLabel(v.reason)}
                      {v.note && `: ${v.note}`} · {v.voided_by_name}, {time(v.voided_at)}
                      {!v.stock_returned && ' · drink was made'}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          <h2>Bills</h2>
          {closed && (
            <p className="muted">This day is closed (count approved), so its bills can no longer be voided.</p>
          )}
          {bills && bills.length === 0 && <p className="muted">No bills on this day.</p>}
          <ul className="bill-list">
            {(bills ?? [])
              .slice()
              .reverse()
              .map((b) => (
                <li key={b.id}>
                  <button onClick={() => setOpen(b)}>
                    <span className="num">{b.invoice_no}</span>
                    <span className="muted">{time(b.sold_at)}</span>
                    <span className={`num right ${b.status === 'void' ? 'struck' : ''}`}>{formatRupees(b.total_paise)}</span>
                    <span className={`status ${b.status === 'void' ? 'voided' : 'synced'}`}>
                      {b.status === 'void' ? 'Voided' : PAYMENT_LABELS[b.payment_mode]}
                    </span>
                  </button>
                </li>
              ))}
          </ul>
        </>
      )}

      {open && (
        <BillSheet
          bill={open}
          canVoid={!closed}
          onClose={() => setOpen(null)}
          onVoided={(b) => {
            setOpen(b);
            void load();
          }}
        />
      )}
    </section>
  );
}

function BillSheet({
  bill,
  canVoid,
  onClose,
  onVoided,
}: {
  bill: ServerBill;
  canVoid: boolean;
  onClose(): void;
  onVoided(b: ServerBill): void;
}) {
  const [voiding, setVoiding] = useState(false);
  const [reason, setReason] = useState<VoidReason | null>(null);
  const [made, setMade] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (!reason) return setError('Choose why this bill is being voided.');
    if (reason === 'other' && !note.trim()) return setError('Write a few words on why.');
    setBusy(true);
    setError(null);
    try {
      onVoided(
        await api.post<ServerBill>(`/bills/${bill.id}/void`, { reason, note: note.trim(), drink_was_made: made }),
      );
      setVoiding(false);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const v = bill.void;
  return (
    <Sheet
      title={<span className="num">{bill.invoice_no}</span>}
      label={`Bill ${bill.invoice_no}`}
      sub={
        <p className="muted">
          {time(bill.sold_at)} · {PAYMENT_LABELS[bill.payment_mode]}
        </p>
      }
      onClose={onClose}
    >

      {v && (
        <p className="void-stamp" role="status">
          <strong>Voided</strong> by {v.voided_by_name} at {time(v.voided_at)}: {voidReasonLabel(v.reason)}
          {v.note && ` (${v.note})`}.{' '}
          {v.stock_returned ? 'Stock was put back.' : 'The drink was made, so stock was not put back.'}
        </p>
      )}

      <table className={`sales-table ${v ? 'struck' : ''}`}>
        <tbody>
          {bill.lines.map((l) => (
            <tr key={l.position}>
              <th scope="row">
                {l.qty} × {l.name_snapshot}
                {l.modifiers.length > 0 && (
                  <span className="muted">
                    {' '}
                    ({l.modifiers.map((m) => `${m.name_snapshot} ${formatPriceDelta(m.price_delta_paise)}`.trim()).join(', ')})
                  </span>
                )}
              </th>
              <td className="num">{formatRupees(l.total_paise)}</td>
            </tr>
          ))}
          <tr className="total-row">
            <th scope="row">Total</th>
            <td className="num">{formatRupees(bill.total_paise)}</td>
          </tr>
        </tbody>
      </table>

      {!v && canVoid && !voiding && (
        <button className="danger" onClick={() => setVoiding(true)}>
          Void this bill
        </button>
      )}

      {!v && voiding && (
        <fieldset className="void-form">
          <legend>Why is it being voided?</legend>
          <div role="radiogroup" aria-label="Reason">
            {VOID_REASONS.map((r) => (
              <label key={r.id} className="check">
                <input type="radio" name="void-reason" checked={reason === r.id} onChange={() => setReason(r.id)} />
                {r.label}
              </label>
            ))}
          </div>
          <label>
            Note {reason === 'other' ? '' : '(optional)'}
            <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
          </label>
          <label className="check">
            <input type="checkbox" checked={made} onChange={(e) => setMade(e.target.checked)} />
            The drink was already made (do not put the stock back)
          </label>
          <p className="muted">
            The bill stays on record with its number, marked voided, and drops out of the day&apos;s sales. This
            cannot be undone.
          </p>
          <div className="sheet-actions">
            <button className="danger" disabled={busy} onClick={() => void confirm()}>
              Void {formatRupees(bill.total_paise)}
            </button>
            <button onClick={() => setVoiding(false)}>Keep the bill</button>
          </div>
        </fieldset>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  );
}

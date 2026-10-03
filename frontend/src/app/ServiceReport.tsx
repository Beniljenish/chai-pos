/**
 * Owner, under Sales: what happened at the tables that day. The leak signals in a
 * restaurant are items removed after they were sent to the kitchen, bills changed
 * after they were printed, and whole orders cancelled. Each shows who and why.
 */
import { useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { api } from './apiClient';

interface ServiceReportData {
  orders: { dine_in: number; takeaway: number; delivery: number };
  cancellations: { order_id: string; label: string; name: string; qty: number; value_paise: number; reason: string; by_name: string; at: string; after_bill: boolean }[];
  cancelled_value_paise: number;
  changed_after_bill: { order_id: string; label: string; bill_prints: number; invoice_no: string | null; removed: { name: string; qty: number; reason: string }[]; added: number }[];
  cancelled_orders: { order_id: string; label: string; reason: string; value_paise: number; by_name: string }[];
  still_open: { order_id: string; label: string; status: string }[];
}

const time = (iso: string) => new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', timeStyle: 'short' }).format(new Date(iso));

export function ServiceReport({ day }: { day: string }) {
  const [r, setR] = useState<ServiceReportData | null>(null);
  useEffect(() => {
    let live = true;
    api
      .get<ServiceReportData>(`/reports/service?business_date=${day}`)
      .then((x) => live && setR(x))
      .catch(() => live && setR(null)); // the sales figures above still stand
    return () => {
      live = false;
    };
  }, [day]);

  if (!r) return null;
  const total = r.orders.dine_in + r.orders.takeaway + r.orders.delivery;
  if (total === 0) return null;

  return (
    <section className="service-report" aria-label="Table service">
      <h2>Table service</h2>
      <p className="muted">
        {r.orders.dine_in} table order{r.orders.dine_in === 1 ? '' : 's'} · {r.orders.takeaway} takeaway · {r.orders.delivery} delivery
      </p>

      {r.still_open.length > 0 && (
        <p className="warn-line">
          Not settled yet: {r.still_open.map((o) => `${o.label}${o.status === 'billed' ? ' (bill printed)' : ''}`).join(', ')}
        </p>
      )}

      {r.changed_after_bill.length > 0 && (
        <>
          <h3 className="alert-head">Changed after the bill was printed ({r.changed_after_bill.length})</h3>
          <ul className="void-list">
            {r.changed_after_bill.map((c) => (
              <li key={c.order_id}>
                <strong>{c.label}</strong>
                {c.invoice_no && <span className="num"> · {c.invoice_no}</span>}
                <br />
                <span className="muted">
                  {[
                    ...c.removed.map((x) => `removed ${x.qty} ${x.name} (${x.reason})`),
                    ...(c.added ? [`${c.added} item${c.added === 1 ? '' : 's'} added`] : []),
                  ].join('; ')}
                  {c.bill_prints > 1 ? ` · bill printed ${c.bill_prints} times` : ''}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {r.cancellations.length > 0 && (
        <>
          <h3>
            Items cancelled after sending to the kitchen: <span className="num">{formatRupees(r.cancelled_value_paise)}</span>
          </h3>
          <ul className="void-list">
            {r.cancellations.map((c, i) => (
              <li key={`${c.order_id}-${i}`} className={c.after_bill ? 'after-bill' : ''}>
                <span>
                  {c.qty} × {c.name}
                </span>{' '}
                <span className="num">{formatRupees(c.value_paise)}</span> · {c.label}
                <br />
                <span className="muted">
                  {c.reason} · {c.by_name}, {time(c.at)}
                  {c.after_bill ? ' · after the bill' : ''}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {r.cancelled_orders.length > 0 && (
        <>
          <h3>Orders cancelled ({r.cancelled_orders.length})</h3>
          <ul className="void-list">
            {r.cancelled_orders.map((c) => (
              <li key={c.order_id}>
                <strong>{c.label}</strong> <span className="num">{formatRupees(c.value_paise)}</span>
                <br />
                <span className="muted">
                  {c.reason} · {c.by_name}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

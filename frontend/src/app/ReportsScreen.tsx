/**
 * Owner, Manage → Reports (README, "Phase 7"): sales over a date range, the
 * month's GST summary in GSTR-1 shape, and what the stock is worth. Every table
 * can be downloaded as a CSV for the accountant.
 */
import { useCallback, useEffect, useState } from 'react';
import { businessDate } from '../lib/billing';
import { formatRupees } from '../lib/gst';
import { formatQty, type BaseUnit } from '../lib/qty';
import { csvRupees, gstTables, presets, toCsv, type GstSummary } from '../lib/reports';
import { dayLabel, hourBars, hourLabel, PAYMENT_LABELS } from '../lib/sales';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading, LoadError } from './Status';

function download(name: string, rows: (string | number)[][]) {
  const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Loads `path` whenever it changes; null while loading. */
function useReport<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    if (!path) return;
    setData(null);
    try {
      setData(await api.get<T>(path));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [path]);
  useEffect(() => {
    void load();
  }, [load]);
  return { data, error, load };
}

export function ReportsScreen() {
  return (
    <section className="reports">
      <header className="manage-head">
        <h1>Reports</h1>
      </header>
      <RangeReport />
      <GstReport />
      <StockValue />
    </section>
  );
}

interface RangeData {
  from: string;
  to: string;
  bills: number;
  total_paise: number;
  gst_paise: number;
  days: { business_date: string; bills: number; total_paise: number }[];
  items: { name: string; qty: number; total_paise: number }[];
  by_hour: { hour: number; bills: number; total_paise: number }[];
  by_mode: { mode: string; bills: number; total_paise: number }[];
  voids: { bills: number; total_paise: number };
}

function RangeReport() {
  const today = businessDate(new Date());
  const quick = presets(today);
  const [range, setRange] = useState({ from: quick[0].from, to: quick[0].to });
  const valid = range.from <= range.to;
  const { data, error, load } = useReport<RangeData>(valid ? `/reports/range?from=${range.from}&to=${range.to}` : null);
  const maxDay = Math.max(1, ...(data?.days.map((d) => d.total_paise) ?? [1]));

  return (
    <section aria-labelledby="range-title">
      <h2 id="range-title">Sales over time</h2>
      <div className="chips" role="group" aria-label="Period">
        {quick.map((p) => (
          <button
            key={p.label}
            className="chip"
            aria-pressed={range.from === p.from && range.to === p.to}
            onClick={() => setRange({ from: p.from, to: p.to })}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="range-dates">
        <label>
          From
          <input type="date" value={range.from} max={today} onChange={(e) => setRange({ ...range, from: e.target.value })} />
        </label>
        <label>
          To
          <input type="date" value={range.to} max={today} onChange={(e) => setRange({ ...range, to: e.target.value })} />
        </label>
      </div>
      {!valid && <p className="error">The end date is before the start date.</p>}
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {valid && !data && !error && <Loading />}
      {data && (
        <>
          <p className="sales-total">
            <span className="big num">{formatRupees(data.total_paise)}</span>
            <br />
            {data.bills} bills · GST {formatRupees(data.gst_paise)}
            {data.voids.bills > 0 && ` · ${data.voids.bills} voided (${formatRupees(data.voids.total_paise)}, not included)`}
          </p>
          <p>
            {data.by_mode.map((m) => `${PAYMENT_LABELS[m.mode] ?? m.mode} ${formatRupees(m.total_paise)}`).join(' · ')}
          </p>
          <h3>By day</h3>
          <ul className="hour-bars day-bars">
            {data.days.map((d) => (
              <li key={d.business_date}>
                <span className="hour">{dayLabel(d.business_date, today)}</span>
                <span className="bar" aria-hidden="true">
                  <span style={{ width: `${Math.round((d.total_paise / maxDay) * 100)}%` }} />
                </span>
                <span className="num">{formatRupees(d.total_paise)}</span>
              </li>
            ))}
          </ul>
          <h3>Items</h3>
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
              {data.items.map((i) => (
                <tr key={i.name}>
                  <th scope="row">{i.name}</th>
                  <td className="num">{i.qty}</td>
                  <td className="num">{formatRupees(i.total_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>By hour of the day</h3>
          <ul className="hour-bars">
            {hourBars(data.by_hour).map((h) => (
              <li key={h.hour}>
                <span className="hour">{hourLabel(h.hour)}</span>
                <span className="bar" aria-hidden="true">
                  <span style={{ width: `${h.pct}%` }} />
                </span>
                <span className="num">{formatRupees(h.total_paise)}</span>
              </li>
            ))}
          </ul>
          <div className="sheet-actions">
            <button
              onClick={() =>
                download(`sales-by-day-${data.from}-to-${data.to}.csv`, [
                  ['Date', 'Bills', 'Sales (Rs)'],
                  ...data.days.map((d) => [d.business_date, d.bills, csvRupees(d.total_paise)]),
                ])
              }
            >
              Download days (CSV)
            </button>
            <button
              onClick={() =>
                download(`sales-by-item-${data.from}-to-${data.to}.csv`, [
                  ['Item', 'Qty', 'Sales (Rs)'],
                  ...data.items.map((i) => [i.name, i.qty, csvRupees(i.total_paise)]),
                ])
              }
            >
              Download items (CSV)
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function GstReport() {
  const [month, setMonth] = useState(businessDate(new Date()).slice(0, 7));
  const { data, error, load } = useReport<GstSummary>(/^\d{4}-\d{2}$/.test(month) ? `/reports/gst?month=${month}` : null);
  const tables = data ? gstTables(data) : null;
  return (
    <section aria-labelledby="gst-title">
      <h2 id="gst-title">GST for a month</h2>
      <label>
        Month
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
      </label>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {!data && !error && <Loading />}
      {data && tables && (
        <>
          {data.gst_type !== 'regular' && (
            <p className="warn">
              This shop is {data.gst_type === 'composition' ? 'under the composition scheme (it files CMP-08, not GSTR-1)' : 'not registered for GST'}.
              The totals are here for your records.
            </p>
          )}
          <p>
            {data.totals.invoices} invoices · {formatRupees(data.totals.invoice_value_paise)} · taxable{' '}
            {formatRupees(data.totals.taxable_paise)} · CGST {formatRupees(data.totals.cgst_paise)} · SGST{' '}
            {formatRupees(data.totals.sgst_paise)}
            {data.nil_rated_paise > 0 && ` · nil-rated ${formatRupees(data.nil_rated_paise)}`}
          </p>
          <h3>B2C (small) by rate</h3>
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
              {data.b2cs.map((r) => (
                <tr key={r.rate_bp}>
                  <th scope="row">{r.rate_bp / 100}%</th>
                  <td className="num">{formatRupees(r.taxable_paise)}</td>
                  <td className="num">{formatRupees(r.cgst_paise)}</td>
                  <td className="num">{formatRupees(r.sgst_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>HSN summary</h3>
          <table className="sales-table">
            <tbody>
              {data.hsn.map((r) => (
                <tr key={`${r.hsn_sac}-${r.rate_bp}`}>
                  <th scope="row">
                    {r.hsn_sac} <span className="muted">{r.description}</span>
                  </th>
                  <td className="num">{r.qty}</td>
                  <td className="num">{formatRupees(r.total_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Invoices issued</h3>
          <ul className="void-list doc-list">
            {data.documents.map((d) => (
              <li key={d.series} className={d.missing ? 'after-bill' : ''}>
                <span className="num">
                  {d.from} to {d.to}
                </span>
                : {d.total} numbers, {d.cancelled} cancelled, {d.net_issued} issued
                {d.missing > 0 && <strong className="error"> · {d.missing} not on the server (see Tablets)</strong>}
              </li>
            ))}
          </ul>
          <div className="sheet-actions">
            <button onClick={() => download(`gstr1-b2cs-${data.month}.csv`, tables.b2cs)}>B2CS (CSV)</button>
            <button onClick={() => download(`gstr1-hsn-${data.month}.csv`, tables.hsn)}>HSN (CSV)</button>
            <button onClick={() => download(`gstr1-docs-${data.month}.csv`, tables.docs)}>Documents (CSV)</button>
          </div>
          <p className="muted">
            HSN codes are each item&apos;s code today. Check the figures with your accountant before filing.
          </p>
        </>
      )}
    </section>
  );
}

interface StockValueData {
  items: {
    ingredient_id: string;
    name: string;
    base_unit: BaseUnit;
    on_hand: string;
    unit_cost_paise: string;
    value_paise: number;
    negative: boolean;
    no_cost: boolean;
  }[];
  total_paise: number;
}

function StockValue() {
  const { data, error, load } = useReport<StockValueData>('/reports/stock-value');
  return (
    <section aria-labelledby="value-title">
      <h2 id="value-title">Stock value</h2>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {!data && !error && <Loading />}
      {data && (
        <>
          <p>
            On the shelf now, at the latest purchase price: <strong className="num">{formatRupees(data.total_paise)}</strong>
          </p>
          <table className="sales-table">
            <tbody>
              {data.items.map((i) => (
                <tr key={i.ingredient_id}>
                  <th scope="row">
                    {i.name}
                    {i.negative && <span className="error"> · below zero</span>}
                    {i.no_cost && !i.negative && Number(i.on_hand) > 0 && <span className="muted"> · no price yet</span>}
                  </th>
                  <td className="num">{formatQty(i.on_hand, i.base_unit)}</td>
                  <td className="num">{formatRupees(i.value_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="sheet-actions">
            <button
              onClick={() =>
                download(`stock-value-${businessDate(new Date())}.csv`, [
                  ['Item', 'On hand', 'Unit', 'Value (Rs)'],
                  ...data.items.map((i) => [i.name, i.on_hand, i.base_unit, csvRupees(i.value_paise)]),
                ])
              }
            >
              Download (CSV)
            </button>
          </div>
        </>
      )}
    </section>
  );
}

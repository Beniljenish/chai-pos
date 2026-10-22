/**
 * The food court operator's overview (README, "9.21"): every outlet side by side, the busy hours,
 * and the settlement sheet to pay from. English only, like the rest of this page.
 */
import { useEffect, useState } from 'react';
import { AdminError, adminApi } from '../lib/adminApi';
import { formatRupees } from '../lib/gst';
import { hourLabel, settlementCsv, shade, type Overview } from '../lib/operator';
import { presets, toCsv } from '../lib/reports';
import { feePercent } from '../lib/statement';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

export function AdminOverview({ token, onSignedOut }: { token: string; onSignedOut(): void }) {
  const ranges = presets(today());
  const [range, setRange] = useState(ranges[0]);
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    adminApi.overview(token, range.from, range.to).then(
      (d) => live && (setData(d), setError(null)),
      (e) => {
        if (!live) return;
        if (e instanceof AdminError && e.status === 401) onSignedOut();
        else setError(e instanceof AdminError ? e.message : 'Could not reach the server.');
      },
    );
    return () => void (live = false);
  }, [token, range, onSignedOut]);

  async function settlement() {
    try {
      const { rows } = await adminApi.settlement(token);
      const url = URL.createObjectURL(new Blob([toCsv(settlementCsv(rows))], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `settlement-${today()}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      if (e instanceof AdminError && e.status === 401) onSignedOut();
      else setError('Could not make the settlement sheet.');
    }
  }

  if (data && data.courts.length === 0) return null;
  return (
    <section className="admin-court" aria-label="Overview">
      <h2>Overview</h2>
      <div className="fc-ranges" role="group" aria-label="Dates">
        {ranges.map((r) => (
          <button key={r.label} className={r.label === range.label ? 'primary' : 'quiet'} onClick={() => setRange(r)}>
            {r.label}
          </button>
        ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data?.courts.map((c) => {
        const max = Math.max(0, ...c.heatmap.flat());
        return (
          <div key={c.court_id} className="court-overview">
            <h3>{c.court}</h3>
            <p>
              Sales <strong className="num">{formatRupees(c.totals.sales_paise)}</strong> · fee kept{' '}
              <strong className="num">{formatRupees(c.totals.fee_paise)}</strong> · {c.totals.orders} orders
            </p>
            <table className="admin-score" aria-label={`${c.court} scorecard`}>
              <thead>
                <tr>
                  <th>Outlet</th>
                  <th>Sales</th>
                  <th>Fee</th>
                  <th>Orders</th>
                  <th>Rating</th>
                  <th>Wait</th>
                  <th>Cancelled</th>
                </tr>
              </thead>
              <tbody>
                {c.outlets.map((o) => (
                  <tr key={o.outlet_id}>
                    <td>{o.name}</td>
                    <td className="num">{formatRupees(o.sales_paise)}</td>
                    <td className="num">
                      {formatRupees(o.fee_paise)} <small className="muted">({feePercent(o.fee_bp)})</small>
                    </td>
                    <td className="num">{o.orders}</td>
                    <td>{o.rating === null ? '–' : `${o.rating} ★ (${o.rating_count})`}</td>
                    <td className="num">{o.avg_wait_min === null ? '–' : `${Math.round(o.avg_wait_min)} min`}</td>
                    <td className="num">{o.cancel_rate_pct === null ? '–' : `${o.cancel_rate_pct}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">A dash means there is nothing to base it on yet (no collected orders, no ratings).</p>
            {c.busiest.length > 0 ? (
              <>
                <p>
                  Busiest:{' '}
                  {c.busiest.map((b) => `${b.weekday} ${hourLabel(b.hour)} (${b.orders})`).join(' · ')}
                </p>
                <div className="heatmap" role="img" aria-label={`${c.court} orders by weekday and hour`}>
                  {c.heatmap.map((row, wd) => (
                    <div key={wd} className="heat-row">
                      <span className="heat-day">{DAYS[wd]}</span>
                      {row.map((n, h) => (
                        <i key={h} className={`heat heat-${shade(n, max)}`} title={`${DAYS[wd]} ${hourLabel(h)}: ${n}`} />
                      ))}
                    </div>
                  ))}
                  <div className="heat-row heat-scale">
                    <span className="heat-day" />
                    {[0, 6, 12, 18, 23].map((h) => (
                      <small key={h} style={{ gridColumn: `${h + 2} / span 4` }}>
                        {hourLabel(h)}
                      </small>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <p className="muted">No orders in these days.</p>
            )}
          </div>
        );
      })}
      <button onClick={() => void settlement()}>Download settlement sheet (CSV)</button>
    </section>
  );
}

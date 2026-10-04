/** Owner: SOP adherence over the last 30 closed days. Is the recipe wrong, or the shift? */
import { useCallback, useEffect, useState } from 'react';
import { adherenceWords, sparkPoints, sparkY100, trendVerdict, VERDICT_WORDS } from '../lib/dayend';
import { formatRupees } from '../lib/gst';
import type { AdherenceTrend as Trend } from '../lib/types';
import { api } from './apiClient';
import { Loading, LoadError } from './Status';
import { explainError } from './errors';

const W = 120;
const H = 32;

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(
    new Date(`${iso}T00:00:00Z`),
  );

function Spark({ days, points, name }: { days: string[]; points: Trend['lines'][number]['points']; name: string }) {
  const pts = sparkPoints(days, points, W, H);
  const y100 = sparkY100(H);
  return (
    <svg
      className="spark"
      viewBox={`-6 -6 ${W + 12} ${H + 12}`}
      width={W + 12}
      height={H + 12}
      role="img"
      aria-label={`${name}: adherence by day, 100% is the recipe`}
    >
      <line className="spark-ref" x1={0} x2={W} y1={y100} y2={y100} />
      {pts.length > 1 && <polyline className="spark-line" points={pts.map((p) => `${p.x},${p.y}`).join(' ')} />}
      {pts.map((p) => (
        <g key={p.date}>
          <circle className="spark-dot" cx={p.x} cy={p.y} r={3} />
          {/* a bigger, invisible target carries the tooltip */}
          <circle className="spark-hit" cx={p.x} cy={p.y} r={8}>
            <title>{`${shortDate(p.date)}: ${p.pct.toFixed(1)}%`}</title>
          </circle>
        </g>
      ))}
    </svg>
  );
}

export function AdherenceTrend() {
  const [trend, setTrend] = useState<Trend | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTrend(await api.get<Trend>('/reports/adherence?days=30'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  if (error && !trend) return <LoadError error={error} onRetry={() => void load()} />;
  if (!trend) return <Loading />;
  return (
    <section className="trend" aria-labelledby="trend-title">
      <h2 id="trend-title">Recipe adherence, last 30 days</h2>
      {trend.lines.length === 0 ? (
        <p className="empty">
          {trend.closed_days.length === 0
            ? "No closed days yet. Approve a day's count and it shows here."
            : 'Nothing counted was sold or made on the closed days, so there is no recipe use to compare.'}
        </p>
      ) : (
        <>
          <p className="muted">
            {trend.closed_days.length} closed {trend.closed_days.length === 1 ? 'day' : 'days'}.{' '}
            {trend.overall_pct !== null && (
              <>
                Overall, by value: <strong className="num">{trend.overall_pct}%</strong>{' '}
                ({adherenceWords(trend.overall_pct)?.toLowerCase()}).
              </>
            )}{' '}
            100% means staff used exactly what the recipe says.
          </p>
          <ul className="trend-list">
            {trend.lines.map((l) => {
              const verdict = trendVerdict(l.points.map((p) => p.adherence_pct));
              return (
                <li key={l.ingredient_id}>
                  <div className="trend-head">
                    <strong>{l.name}</strong>
                    <span className="num">{l.adherence_pct === null ? '–' : `${l.adherence_pct}%`}</span>
                  </div>
                  <Spark days={trend.closed_days} points={l.points} name={l.name} />
                  <p className={`trend-verdict ${verdict}`}>
                    {VERDICT_WORDS[verdict]}
                    {l.variance_paise < 0 && <> · missing {formatRupees(-l.variance_paise)} in total</>}
                  </p>
                  <details>
                    <summary>By day</summary>
                    <ul className="trend-days">
                      {l.points.map((p) => (
                        <li key={p.business_date}>
                          <span>{shortDate(p.business_date)}</span>
                          <span className="num">{p.adherence_pct === null ? '–' : `${p.adherence_pct}%`}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

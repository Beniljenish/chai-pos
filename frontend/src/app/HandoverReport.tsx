/** Owner: the day's gap on milk and fruit, split at each shift change (Phase 10.3). */
import { useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { formatDelta } from '../lib/qty';
import type { HandoverReport as Report } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';

const time = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', timeStyle: 'short' }).format(new Date(iso));

export function HandoverReport({ day, refreshKey }: { day: string; refreshKey: number }) {
  const [rep, setRep] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Report>(`/reports/handover?business_date=${day}`).then(
      (r) => {
        setRep(r);
        setError(null);
      },
      (e) => setError(explainError(e)),
    );
  }, [day, refreshKey]);

  if (error) return <p className="error">{error}</p>;
  if (!rep || rep.periods.length === 0) return null; // no shift counts that day
  return (
    <section className="report handover-report" aria-labelledby="handover-report-title">
      <h2 id="handover-report-title">Shift handovers</h2>
      <p className="muted">
        Milk and fruit are counted at each shift change, so the day&apos;s gap is split by when it opened. With two
        counters open, everyone on duty in that time is listed.
      </p>
      <ol className="periods">
        {rep.periods.map((p) => (
          <li key={p.end}>
            <div className="period-head">
              <strong>
                {time(p.start)} – {p.is_day_end ? 'day end' : time(p.end)}
              </strong>
              <span className={`num ${p.gap_here_paise < 0 ? 'neg' : ''}`}>
                {p.gap_here_paise === 0 ? 'No gap' : formatRupees(p.gap_here_paise)}
              </span>
            </div>
            <p className="muted">
              {p.on_duty.length ? `On duty: ${p.on_duty.join(', ')}` : 'No shift open'}
              {p.counted_by_name && ` · counted by ${p.counted_by_name}`}
            </p>
            <ul className="period-lines">
              {p.lines.map((l) => (
                <li key={l.ingredient_id}>
                  <span>{l.name}</span>
                  <span className={`num ${Number(l.gap_here) < 0 ? 'neg' : ''}`}>
                    {Number(l.gap_here) === 0 ? 'exact' : formatDelta(l.gap_here, l.base_unit)}
                  </span>
                  <span className="num muted">{l.gap_here_paise ? formatRupees(l.gap_here_paise) : ''}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}

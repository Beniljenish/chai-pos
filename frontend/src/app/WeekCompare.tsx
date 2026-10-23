/**
 * Sales: the chosen day beside the same weekday a week earlier, and the last
 * seven days against the seven before. Read-only, one /reports/range call.
 */
import { t } from '../lib/i18n';
import { useEffect, useState } from 'react';
import { change, changeText, weekPairs, type DayTotal } from '../lib/compare';
import { formatRupees } from '../lib/gst';
import { shiftDay } from '../lib/sales';
import { api } from './apiClient';

const weekday = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat('en-IN', { weekday: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(y, m - 1, d)));
};

export function WeekCompare({ day, today }: { day: string; today: string }) {
  // Today is still going: a part-day against a full day last week is not a fair comparison.
  const partDay = day === today;
  const [days, setDays] = useState<DayTotal[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setDays(null);
    setFailed(false);
    api
      .get<{ days: DayTotal[] }>(`/reports/range?from=${shiftDay(day, -13)}&to=${day}`)
      .then((r) => live && setDays(r.days))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [day]);

  if (failed) return <p className="muted">Last week&apos;s comparison could not load.</p>;
  if (!days) return null;

  const pairs = weekPairs(days, day, shiftDay);
  const last = pairs[pairs.length - 1];
  const bills = (iso: string) => days.find((d) => d.business_date === iso)?.bills ?? 0;
  const money = change(last.now, last.before);
  const count = change(bills(day), bills(shiftDay(day, -7)));
  if (pairs.every((p) => p.now === 0 && p.before === 0)) return null;
  const top = Math.max(1, ...pairs.flatMap((p) => [p.now, p.before]));
  const tone = (c: typeof money) => (c.direction === 'down' ? 'down' : c.direction === 'up' ? 'up' : 'same');

  return (
    <section className="week-compare" aria-label="Compared with last week">
      <p className="week-line">
        {partDay ? (
          <span className="delta same">{t("Today so far")}</span>
        ) : (
          <span className={`delta ${tone(money)}`}>{changeText(money) || 'No sales to compare'}</span>
        )}
        <span>
          {partDay ? 'Last' : 'vs last'} {weekday(shiftDay(day, -7))}
          {partDay ? ', full day' : ''}: <strong className="num">{formatRupees(last.before)}</strong>
        </span>
      </p>
      <div
        className="week-bars"
        role="img"
        aria-label={`Sales each of the last 7 days, against the same day the week before. ${pairs
          .map((p) => `${weekday(p.date)} ${formatRupees(p.now)} against ${formatRupees(p.before)}`)
          .join('; ')}`}
      >
        {pairs.map((p) => (
          <div key={p.date} className="week-day" aria-hidden="true">
            <span className="then" style={{ height: `${Math.round((p.before / top) * 100)}%` }} />
            <span className="now" style={{ height: `${Math.round((p.now / top) * 100)}%` }} />
            <small>{weekday(p.date).slice(0, 2)}</small>
          </div>
        ))}
      </div>
      <p className="week-legend muted" aria-hidden="true">
        <span className="swatch then" /> Week before <span className="swatch now" /> This week
        {!partDay && changeText(count) && (
          <span className={`delta small ${tone(count)}`}>Bills {changeText(count)}</span>
        )}
      </p>
    </section>
  );
}

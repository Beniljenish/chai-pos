/** Day end. Owner: wastage, count, variance and approval. Cashier: wastage and the blind count only. */
import { useCallback, useState } from 'react';
import { countableDays } from '../lib/dayend';
import { AdherenceTrend } from './AdherenceTrend';
import { CountPanel } from './CountPanel';
import { DayReport } from './DayReport';
import { PrepPanel } from './PrepPanel';
import { useSession } from './session';
import { WastagePanel } from './WastagePanel';

export function DayEndScreen() {
  const { user } = useSession();
  const isOwner = user?.role === 'owner';
  const days = countableDays(new Date());
  const [day, setDay] = useState(days[0].date);
  const [refresh, setRefresh] = useState(0); // count changed -> report reloads
  const [closed, setClosed] = useState(0); // day approved -> count reloads
  const bump = useCallback(() => setRefresh((n) => n + 1), []);
  const reloadCount = useCallback(() => setClosed((n) => n + 1), []);

  return (
    <section className="dayend">
      <header className="manage-head">
        <h1>{isOwner ? 'Day end' : 'Stock tasks'}</h1>
      </header>
      {!isOwner && <PrepPanel />}
      <WastagePanel onLogged={bump} />
      <div className="segmented day-pick" role="radiogroup" aria-label="Which day">
        {days.map((d) => (
          <button key={d.date} role="radio" aria-checked={day === d.date} onClick={() => setDay(d.date)}>
            {d.label}
          </button>
        ))}
      </div>
      <p className="muted">Closing after midnight? Choose yesterday: the count belongs to the day you are closing.</p>
      <CountPanel key={`${day}-count`} day={day} refreshKey={closed} onStatus={bump} />
      {isOwner && <DayReport key={`${day}-report`} day={day} refreshKey={refresh} onApproved={reloadCount} />}
      {isOwner && <AdherenceTrend key={`trend-${closed}`} />}
    </section>
  );
}

/**
 * Phase 10.3: at a shift change, count the "every shift" items (milk, fruit), blind.
 * Needs the internet (packs are converted on the server, like the day-end count);
 * offline, the shift still ends and the day-end count still covers the day.
 */
import { useEffect, useState } from 'react';
import { packsPayload } from '../lib/qty';
import type { Ingredient } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { PackEntry } from './PackEntry';

type Entry = { counts: Record<string, number>; loose: string; touched: boolean };
export type HandoverState = 'loading' | 'none' | 'todo' | 'sent' | 'skipped';

export function HandoverCount({ shiftId, onState }: { shiftId: string; onState(s: HandoverState): void }) {
  const [items, setItems] = useState<Ingredient[] | null>(null);
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const [state, setState] = useState<HandoverState>('loading');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (s: HandoverState) => {
    setState(s);
    onState(s);
  };

  useEffect(() => {
    api.get<Ingredient[]>('/ingredients').then(
      (all) => {
        const shift = all.filter((i) => i.is_active && i.count_frequency === 'shift');
        setItems(shift);
        set(shift.length ? 'todo' : 'none');
      },
      () => set('skipped'), // offline: nothing to block on
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (state === 'loading' || state === 'none') return null;
  if (state === 'skipped')
    return <p className="muted">No connection, so the milk and fruit count is skipped this time. The day-end count still covers it.</p>;
  if (state === 'sent') return <p className="ok">Milk and fruit counted. Now the drawer.</p>;

  const entry = (id: string): Entry => entries[id] ?? { counts: {}, loose: '', touched: false };
  const touch = (id: string, patch: Partial<Entry>) =>
    setEntries((e) => ({ ...e, [id]: { ...entry(id), ...patch, touched: true } }));
  const missing = items!.filter((i) => !entry(i.id).touched);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.post('/handover-counts', {
        shift_id: shiftId,
        lines: items!.map((i) => ({
          ingredient_id: i.id,
          packs: packsPayload(entry(i.id).counts),
          loose_qty: String(Number(entry(i.id).loose) || 0),
        })),
      });
      set('sent');
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="handover" aria-labelledby="handover-title">
      <h3 id="handover-title">First, count these</h3>
      <p className="muted">Count what is on the shelf now, before the next shift starts using it.</p>
      <ul className="count-list">
        {items!.map((i) => {
          const e = entry(i.id);
          return (
            <li key={i.id} className={e.touched ? 'done' : ''}>
              <strong>{i.name}</strong>
              <PackEntry
                ingredient={i}
                counts={e.counts}
                loose={e.loose}
                onCounts={(counts) => touch(i.id, { counts })}
                onLoose={(loose) => touch(i.id, { loose })}
              />
            </li>
          );
        })}
      </ul>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" disabled={busy || missing.length > 0} onClick={() => void send()}>
          {missing.length ? `Count ${missing.length} more` : 'Send count'}
        </button>
        <button onClick={() => set('skipped')}>Skip this time</button>
      </div>
    </section>
  );
}

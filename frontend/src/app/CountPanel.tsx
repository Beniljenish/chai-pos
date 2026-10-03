/**
 * The day-end count. Blind: it never shows what the system expects. Items
 * outside tolerance come back once as "count again", with no numbers.
 */
import { useCallback, useEffect, useState } from 'react';
import { mustCount } from '../lib/dayend';
import { formatQty, packsPayload, packsToBase } from '../lib/qty';
import type { CountSheet, DayStatus, Ingredient, SheetItem } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { PackEntry } from './PackEntry';
import { useSession } from './session';

interface Entry {
  counts: Record<string, number>;
  loose: string;
  touched: boolean;
}

const asIngredient = (s: SheetItem): Ingredient => ({
  id: s.ingredient_id,
  name: s.name,
  kind: s.kind,
  base_unit: s.base_unit,
  pack_units: s.pack_units,
  scales_with_size: true,
  is_active: true,
  reorder_level: null,
});

export function CountPanel({
  day,
  refreshKey = 0,
  onStatus,
}: {
  day: string;
  refreshKey?: number;
  onStatus?: (s: DayStatus) => void;
}) {
  const { sync } = useSession();
  const [sheet, setSheet] = useState<CountSheet | null>(null);
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const [recount, setRecount] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [again, setAgain] = useState(false); // re-open a count already sent

  const load = useCallback(async () => {
    try {
      const s = await api.get<CountSheet>(`/day-counts/${day}/sheet`);
      setSheet(s);
      setRecount(s.items.filter((i) => i.recount).map((i) => i.ingredient_id));
      onStatus?.(s.status);
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, [day, onStatus]);

  useEffect(() => {
    setEntries({});
    setAgain(false);
    void load();
  }, [load, refreshKey]);

  const pending = sync?.pending ?? 0;
  if (error && !sheet) return <p className="error">{error}</p>;
  if (!sheet) return <p className="muted">Loading…</p>;

  if (sheet.status === 'approved')
    return (
      <section className="count" aria-labelledby="count-title">
        <h2 id="count-title">Day-end count</h2>
        <p className="ok">This day is closed. The owner approved the count.</p>
      </section>
    );

  const recounting = recount.length > 0;
  if (sheet.status === 'submitted' && !recounting && !again)
    return (
      <section className="count" aria-labelledby="count-title">
        <h2 id="count-title">Day-end count</h2>
        <p className="ok" role="status">
          Count sent to the owner.
        </p>
        <button onClick={() => setAgain(true)}>Count again</button>
      </section>
    );
  const shown = recounting ? sheet.items.filter((i) => recount.includes(i.ingredient_id)) : sheet.items;
  const entry = (id: string): Entry => entries[id] ?? { counts: {}, loose: '', touched: false };
  const set = (id: string, patch: Partial<Entry>) =>
    setEntries((e) => ({ ...e, [id]: { ...entry(id), ...patch, touched: true } }));
  const missing = shown.filter((i) => (recounting || mustCount(i.count_frequency)) && !entry(i.ingredient_id).touched);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const lines = shown
        .filter((i) => entry(i.ingredient_id).touched)
        .map((i) => ({
          ingredient_id: i.ingredient_id,
          packs: packsPayload(entry(i.ingredient_id).counts),
          loose_qty: String(Number(entry(i.ingredient_id).loose) || 0),
        }));
      const res = await api.post<{ status: DayStatus; recount: string[] }>(`/day-counts/${day}/counts`, { lines });
      setEntries({});
      setRecount(res.recount);
      setAgain(false);
      await load();
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="count" aria-labelledby="count-title">
      <h2 id="count-title">{recounting ? 'Please count these again' : 'Day-end count'}</h2>
      {again && <p className="muted">Counting again replaces what was sent, item by item.</p>}
      {recounting ? (
        <p className="warn">
          Count {recount.length === 1 ? 'this item' : 'these items'} once more, carefully, from the shelf. Do not copy
          the first number.
        </p>
      ) : (
        <p className="muted">
          Count what is on the shelf now. Enter packs and loose amounts; the app adds them up. Use “It is zero” for an
          empty shelf.
        </p>
      )}
      {pending > 0 && (
        <p className="warn" role="alert">
          {pending} bill{pending === 1 ? ' is' : 's are'} still waiting to be sent from this tablet. Connect to the
          internet first: the count must include every bill.
        </p>
      )}
      <ul className="count-list">
        {shown.map((i) => {
          const e = entry(i.ingredient_id);
          const ing = asIngredient(i);
          const total = packsToBase(i.pack_units, e.counts, Number(e.loose) || 0);
          return (
            <li key={i.ingredient_id} className={e.touched ? 'done' : ''}>
              <div className="count-head">
                <strong>{i.name}</strong>
                <span className="muted">
                  {!mustCount(i.count_frequency) && !recounting && 'weekly · optional'}
                  {i.counted && !e.touched && !recounting && ' counted'}
                </span>
              </div>
              <PackEntry
                ingredient={ing}
                counts={e.counts}
                loose={e.loose}
                onCounts={(c) => set(i.ingredient_id, { counts: c })}
                onLoose={(l) => set(i.ingredient_id, { loose: l })}
              />
              <div className="count-actions">
                <button className="quiet" onClick={() => set(i.ingredient_id, { counts: {}, loose: '0' })}>
                  It is zero
                </button>
                {e.touched && <span className="ok">✓ {formatQty(total, i.base_unit)}</span>}
              </div>
            </li>
          );
        })}
      </ul>
      {missing.length > 0 && (
        <p className="muted">Still to count: {missing.map((m) => m.name).join(', ')}</p>
      )}
      <button
        className="primary"
        disabled={busy || pending > 0 || missing.length > 0 || !shown.some((i) => entry(i.ingredient_id).touched)}
        onClick={() => void submit()}
      >
        {recounting ? 'Send recount' : 'Send count'}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

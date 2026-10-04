/** Every known loss gets a reason, in a few taps, so it is not "missing" at day end. */
import { useCallback, useEffect, useState } from 'react';
import { REASONS, reasonLabel } from '../lib/dayend';
import { formatRupees } from '../lib/gst';
import { formatQty, packsToBase } from '../lib/qty';
import type { Ingredient, MenuItem, WastageReason, WastageRow } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { PackEntry } from './PackEntry';
import { useSession } from './session';

export function WastagePanel({ onLogged }: { onLogged?: () => void }) {
  const { user } = useSession();
  const isOwner = user?.role === 'owner';
  const [kind, setKind] = useState<'drink' | 'ingredient'>('drink');
  const [items, setItems] = useState<MenuItem[]>([]);
  const [ingredients, setIngredients] = useState<Ingredient[]>([]);
  const [target, setTarget] = useState('');
  const [servings, setServings] = useState(1);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loose, setLoose] = useState('');
  const [reason, setReason] = useState<WastageReason | null>(null);
  const [rows, setRows] = useState<WastageRow[]>([]);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const loadToday = useCallback(async () => {
    try {
      setRows(await api.get<WastageRow[]>('/wastage'));
    } catch {
      /* the list is a convenience; recording still works */
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [m, i] = await Promise.all([api.get<MenuItem[]>('/menu-items'), api.get<Ingredient[]>('/ingredients')]);
        setItems(m.filter((x) => x.is_active));
        setIngredients(i.filter((x) => x.is_active));
      } catch (e) {
        setMessage({ ok: false, text: explainError(e) });
      }
    })();
    void loadToday();
  }, [loadToday]);

  const ing = ingredients.find((i) => i.id === target);
  const qty = kind === 'drink' ? servings : ing ? packsToBase(ing.pack_units, counts, Number(loose) || 0) : 0;
  const ready = Boolean(target && reason && qty > 0);

  function reset(nextKind = kind) {
    setKind(nextKind);
    setTarget('');
    setServings(1);
    setCounts({});
    setLoose('');
    setReason(null);
  }

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api.post('/wastage', {
        [kind === 'drink' ? 'menu_item_id' : 'ingredient_id']: target,
        qty: String(qty),
        reason,
      });
      const name = kind === 'drink' ? items.find((m) => m.id === target)?.name : ing?.name;
      setMessage({ ok: true, text: `Recorded: ${kind === 'drink' ? `${qty} × ${name}` : `${formatQty(qty, ing!.base_unit)} ${name}`}, ${reasonLabel(reason!).toLowerCase()}.` });
      reset();
      void loadToday();
      onLogged?.();
    } catch (e) {
      setMessage({ ok: false, text: explainError(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="wastage" aria-labelledby="wastage-title">
      <h2 id="wastage-title">Something wasted?</h2>
      <div className="segmented" role="radiogroup" aria-label="What was wasted">
        <button role="radio" aria-checked={kind === 'drink'} onClick={() => reset('drink')}>
          A drink
        </button>
        <button role="radio" aria-checked={kind === 'ingredient'} onClick={() => reset('ingredient')}>
          An ingredient
        </button>
      </div>
      <label>
        {kind === 'drink' ? 'Which drink' : 'Which ingredient'}
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Choose…</option>
          {(kind === 'drink' ? items : ingredients).map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </select>
      </label>
      {kind === 'drink' && target && (
        <div className="pack-row">
          <strong>How many</strong>
          <div className="stepper">
            <button aria-label="One less" onClick={() => setServings(Math.max(1, servings - 1))}>
              −
            </button>
            <span className="num">{servings}</span>
            <button aria-label="One more" onClick={() => setServings(servings + 1)}>
              +
            </button>
          </div>
        </div>
      )}
      {kind === 'ingredient' && ing && (
        <PackEntry ingredient={ing} counts={counts} loose={loose} onCounts={setCounts} onLoose={setLoose} />
      )}
      {target && (
        <div className="reasons" role="radiogroup" aria-label="Why">
          {REASONS.filter((r) => isOwner || !r.ownerOnly).map((r) => (
            <button key={r.id} role="radio" aria-checked={reason === r.id} className="chip" onClick={() => setReason(r.id)}>
              {r.label}
            </button>
          ))}
        </div>
      )}
      {target && (
        <button className="primary" disabled={!ready || busy} onClick={() => void save()}>
          Record wastage
        </button>
      )}
      {message && (
        <p className={message.ok ? 'ok' : 'error'} role={message.ok ? 'status' : 'alert'}>
          {message.text}
        </p>
      )}
      {rows.length > 0 && (
        <details className="history">
          <summary>
            Today: {rows.length} entr{rows.length === 1 ? 'y' : 'ies'}
            {isOwner &&
              ` · ${formatRupees(rows.reduce((a, r) => a + (r.status === 'rejected' ? 0 : (r.value_paise ?? 0)), 0))}`}
          </summary>
          <ul className="ledger">
            {rows.map((r) => (
              <li key={r.id}>
                <span>
                  {r.is_menu_item ? `${Number(r.qty)} × ${r.name}` : `${formatQty(r.qty, r.base_unit!)} ${r.name}`}
                  <br />
                  <span className="muted">
                    {reasonLabel(r.reason)} · {r.created_by_name}
                  </span>
                  {r.status === 'pending' && <span className="flag wait">Waiting for the owner</span>}
                  {r.status === 'rejected' && <span className="flag bad">Not accepted</span>}
                </span>
                <span />
                <span className="num right">{r.value_paise !== null ? formatRupees(r.value_paise) : ''}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

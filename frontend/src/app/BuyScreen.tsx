/**
 * Owner: tell the app what you bought, by voice, typing or a photo of the bill, and check the draft
 * before it is saved (README, "9.16"). Nothing is saved until "Save": the saving is the ordinary
 * stock-in, one per line, so stock still moves only through the ledger.
 */
import { Hint } from './Hint';
import { useEffect, useState } from 'react';
import {
  draftTotal,
  lineReady,
  showQty,
  withCost,
  withIngredient,
  withQty,
  type Draft,
  type DraftLine,
} from '../lib/aiTypes';
import { rupeesToPaise } from '../lib/foodcourt';
import { formatRupees } from '../lib/gst';
import { t, useLang } from '../lib/i18n';
import { pictureForUpload } from '../lib/image';
import { HttpError } from '../lib/api';
import { api } from './apiClient';
import { explainError } from './errors';
import { Mic } from './Mic';
import { useAiStatus } from './useAi';

interface Ingredient {
  id: string;
  name: string;
  kind: string;
  base_unit: string;
  is_active: boolean;
}

type Saved = 'saved' | { error: string } | { confirm: string };

export function BuyScreen() {
  useLang();
  const [used, setUsed] = useState(0);
  const status = useAiStatus(used);
  const [items, setItems] = useState<Ingredient[]>([]);
  const [text, setText] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [supplier, setSupplier] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<number, Saved>>({});
  const [done, setDone] = useState(0);
  const [draftNo, setDraftNo] = useState(0); // new inputs for a new draft

  useEffect(() => {
    api
      .get<Ingredient[]>('/ingredients')
      .then((all) => setItems(all.filter((i) => i.kind === 'raw' && i.is_active)))
      .catch(() => undefined);
  }, []);

  function take(d: Draft) {
    setDraft(d);
    setLines(d.lines);
    setSupplier(d.supplier);
    setResults({});
    setDone(0);
    setDraftNo((n) => n + 1);
  }

  async function readNote() {
    setBusy(true);
    setError(null);
    try {
      take(await api.post<Draft>('/ai/purchase-draft', { text }));
      setUsed((n) => n + 1);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function readPhoto(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const pic = await pictureForUpload(file);
      if (!pic) {
        setError(t('That file is not a picture the app can send. Take the photo again.'));
        return;
      }
      take(await api.post<Draft>('/ai/bill-draft', { image_base64: pic.base64, media_type: pic.mediaType }));
      setUsed((n) => n + 1);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const setLine = (i: number, next: DraftLine) => setLines((all) => all.map((l, n) => (n === i ? next : l)));
  const ready = lines.length > 0 && lines.every(lineReady);

  /** Take a line out, and move the "saved / needs a look" marks of the lines after it up with them. */
  function removeLine(i: number) {
    setLines((all) => all.filter((_, n) => n !== i));
    setResults((old) =>
      Object.fromEntries(Object.entries(old).filter(([k]) => Number(k) !== i).map(([k, v]) => [Number(k) > i ? Number(k) - 1 : Number(k), v])),
    );
    setDraftNo((n) => n + 1); // the price boxes are uncontrolled: remount them with the right values
  }

  async function saveLine(i: number, confirmLarge: boolean): Promise<boolean> {
    const l = lines[i];
    try {
      await api.post('/stock-in', {
        ingredient_id: l.ingredient_id,
        loose_qty: l.base_qty,
        cost_paise: l.cost_paise,
        supplier,
        confirm_large: confirmLarge,
      });
      setResults((r) => ({ ...r, [i]: 'saved' }));
      return true;
    } catch (e) {
      const d = e instanceof HttpError && e.status === 409 && e.detail && typeof e.detail === 'object' ? (e.detail as { needs?: string; message?: string }) : null;
      setResults((r) => ({ ...r, [i]: d?.needs === 'confirm_large' ? { confirm: d.message ?? '' } : { error: explainError(e) } }));
      return false;
    }
  }

  async function saveAll() {
    setBusy(true);
    let ok = 0;
    for (let i = 0; i < lines.length; i++) {
      if (results[i] === 'saved') {
        ok++;
        continue;
      }
      if (await saveLine(i, false)) ok++;
    }
    setDone(ok);
    setBusy(false);
  }

  const total = draftTotal(lines);
  const allSaved = lines.length > 0 && lines.every((_, i) => results[i] === 'saved');

  return (
    <section className="buy">
      <header className="manage-head">
        <h1>{t('Buy by voice or photo')}</h1>
      </header>
      <Hint>
        {t('Say or type what you bought, or photograph the supplier’s bill. You check the draft, then save. Nothing is saved before that.')}
      </Hint>
      {status && !status.on && (
        <p className="cx-note">{t('The AI helpers are not switched on yet. You can still type a stock-in in Stock.')}</p>
      )}
      {status?.pretend && <p className="cx-note">{t('Pretend mode: simple rules stand in for the AI. Real Tamil and real bills need the real AI.')}</p>}

      {!allSaved && (
        <div className="buy-input">
          <label>
            {t('What did you buy?')}
            <textarea
              value={text}
              rows={3}
              maxLength={1500}
              onChange={(e) => setText(e.target.value)}
              placeholder={t('For example: 20 litre milk 480 rupees, 5 kg sugar 225 rupees')}
            />
          </label>
          <Mic onText={(spoken) => setText(spoken)} />
          <div className="buy-actions">
            <button className="primary" disabled={busy || !status?.on || text.trim().length < 2} onClick={() => void readNote()}>
              {busy ? t('Reading…') : t('Make a draft')}
            </button>
            <label className={`button ${busy || !status?.on ? 'disabled' : ''}`}>
              📷 {t('Photo of the bill')}
              <input
                type="file"
                accept="image/*"
                capture="environment"
                hidden
                disabled={busy || !status?.on}
                onChange={(e) => {
                  void readPhoto(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
            </label>
          </div>
          {status && status.on && (
            <small className="muted">{t('{used} of {limit} AI questions used today', { used: status.used_today, limit: status.daily_limit })}</small>
          )}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {draft && lines.length === 0 && <p className="cx-note">{t('Nothing could be read. Try again, or type it more clearly.')}</p>}
      {draft && lines.length > 0 && (
        <div className="buy-draft">
          <h2>{t('Check the draft')}</h2>
          <label>
            {t('Supplier')}
            <input value={supplier} maxLength={80} onChange={(e) => setSupplier(e.target.value)} />
          </label>
          <ul className="buy-lines">
            {lines.map((l, i) => {
              const r = results[i];
              return (
                <li key={`${draftNo}-${i}`} className={`buy-line ${lineReady(l) ? 'ok' : 'bad'} ${r === 'saved' ? 'done' : ''}`}>
                  <p className="muted">
                    {t('Heard')}: “{l.heard_name}”
                  </p>
                  <label>
                    {t('Stock item')}
                    <select
                      value={l.ingredient_id ?? ''}
                      disabled={r === 'saved'}
                      onChange={(e) => {
                        const it = items.find((x) => x.id === e.target.value);
                        setLine(i, it ? withIngredient(l, it.id, it.name, it.base_unit) : withIngredient(l, null, '', ''));
                      }}
                    >
                      <option value="">{t('Pick one…')}</option>
                      {items.map((it) => (
                        <option key={it.id} value={it.id}>
                          {it.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="buy-pair">
                    <label>
                      {t('Quantity')} {l.base_unit && `(${l.base_unit})`}
                      <input
                        inputMode="decimal"
                        disabled={r === 'saved'}
                        value={l.base_qty === null ? '' : String(Number(l.base_qty))}
                        onChange={(e) => setLine(i, withQty(l, e.target.value))}
                      />
                    </label>
                    <label>
                      {t('Total price (₹)')}
                      <input
                        inputMode="decimal"
                        disabled={r === 'saved'}
                        defaultValue={l.cost_paise ? String(l.cost_paise / 100) : ''}
                        onChange={(e) => setLine(i, withCost(l, rupeesToPaise(e.target.value) ?? 0))}
                      />
                    </label>
                  </div>
                  {l.base_qty !== null && l.base_unit && (
                    <small className="muted">
                      = {showQty(l.base_unit, l.base_qty)} · {formatRupees(l.cost_paise)}
                    </small>
                  )}
                  {l.problems.map((p) => (
                    <p key={p} className="error">
                      {t(p)}
                    </p>
                  ))}
                  {r === 'saved' && <p className="buy-saved">✓ {t('Saved')}</p>}
                  {r && r !== 'saved' && 'error' in r && <p className="error">{r.error}</p>}
                  {r && r !== 'saved' && 'confirm' in r && (
                    <div className="cx-note">
                      <p>{r.confirm || t('This is much more than usual.')}</p>
                      <button onClick={() => void saveLine(i, true)}>{t('Yes, save it anyway')}</button>
                    </div>
                  )}
                  {r !== 'saved' && (
                    <button className="quiet" onClick={() => removeLine(i)}>
                      {t('Remove this line')}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          <p className={draft.total_matches === false ? 'error' : 'muted'}>
            {t('The lines add up to {total}.', { total: formatRupees(total) })}{' '}
            {draft.bill_total_paise !== null &&
              (draft.total_matches && total === draft.bill_total_paise
                ? t('This matches the bill’s total.')
                : t('The bill says {total}. Check the lines.', { total: formatRupees(draft.bill_total_paise) }))}
          </p>
          {!allSaved && (
            <button className="primary" disabled={!ready || busy} onClick={() => void saveAll()}>
              {busy ? t('Saving…') : t('Save {n} stock-ins', { n: lines.length })}
            </button>
          )}
          {allSaved && (
            <div className="cx-note" role="status">
              <strong>{t('All {n} saved.', { n: done || lines.length })}</strong>{' '}
              <button
                className="quiet"
                onClick={() => {
                  setDraft(null);
                  setLines([]);
                  setText('');
                  setResults({});
                }}
              >
                {t('Buy something else')}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

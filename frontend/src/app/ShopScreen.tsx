/**
 * Shop details and GST registration: these decide what every bill is called and
 * whether it charges tax, so each choice says plainly what it will print.
 */
import { useEffect, useState } from 'react';
import { computeBill, formatRate, formatRupees, type GstType } from '../lib/gst';
import { checkGstin, STATES } from '../lib/gstin';
import { api } from './apiClient';
import { explainError } from './errors';
import { MenuPrices } from './MenuPrices';
import { useSession } from './session';

interface Shop {
  id: string;
  name: string;
  gst_type: GstType;
  gstin: string | null;
  state_code: string;
  address: string;
}

const TYPES: { id: GstType; title: string; prints: string; detail: string }[] = [
  {
    id: 'unregistered',
    title: 'Not registered for GST',
    prints: 'Bill',
    detail: 'No GST is charged or printed. For shops below the registration limit.',
  },
  {
    id: 'composition',
    title: 'Composition scheme',
    prints: 'Bill of supply',
    detail:
      'You pay GST yourself on your turnover; customers are not charged tax. Bills show your GSTIN and the line "Composition taxable person, not eligible to collect tax on supplies".',
  },
  {
    id: 'regular',
    title: 'Regular GST',
    prints: 'Tax invoice',
    detail: 'Each bill shows your GSTIN, the taxable value, and CGST and SGST with their rates.',
  },
];

export function ShopScreen() {
  const { catalogue, reloadCatalogue } = useSession();
  const [shop, setShop] = useState<Shop | null>(null);
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [type, setType] = useState<GstType>('unregistered');
  const [gstin, setGstin] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  function fill(s: Shop) {
    setShop(s);
    setName(s.name);
    setAddress(s.address);
    setType(s.gst_type);
    setGstin(s.gstin ?? '');
  }

  useEffect(() => {
    api.get<Shop>('/shop').then(fill, (e) => setError(explainError(e)));
  }, []);

  const needsGstin = type !== 'unregistered';
  const check = gstin.trim() ? checkGstin(gstin) : null;
  const typeChanged = shop !== null && type !== shop.gst_type;
  const dirty =
    shop !== null &&
    (name !== shop.name || address !== shop.address || typeChanged || (gstin.trim().toUpperCase() || null) !== shop.gstin);
  const blocked = (needsGstin && !(check && check.ok)) || (check !== null && !check.ok) || !name.trim();

  // What a typical item would print under the chosen registration.
  const sample = catalogue?.menu_items.find((m) => m.is_active);
  const preview = sample
    ? computeBill(
        [{ unitPricePaise: sample.price_paise, qty: 1, gstRateBp: sample.gst_rate_bp, taxInclusive: sample.tax_inclusive }],
        type,
      )
    : null;

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const body: Record<string, unknown> = { name: name.trim(), address: address.trim(), gst_type: type };
      body.gstin = check && check.ok ? check.gstin : null;
      fill(await api.patch<Shop>('/shop', body));
      await reloadCatalogue(); // this tablet's next bill uses the new registration
      setSaved(true);
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  if (!shop) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;

  return (
    <section className="shop">
      <header className="manage-head">
        <h1>Shop &amp; GST</h1>
      </header>

      <div className="panel-inline">
        <label>
          Shop name (printed on bills)
          <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Address (printed on bills)
          <input value={address} maxLength={500} onChange={(e) => setAddress(e.target.value)} />
        </label>
      </div>

      <fieldset className="gst-types">
        <legend>GST registration</legend>
        {TYPES.map((t) => (
          <label key={t.id} className={`gst-type ${type === t.id ? 'chosen' : ''}`}>
            <input type="radio" name="gst" checked={type === t.id} onChange={() => setType(t.id)} />
            <span>
              <strong>{t.title}</strong>
              <span className="muted"> · prints “{t.prints}”</span>
              <br />
              <span className="gst-detail">{t.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <label>
        GSTIN {needsGstin ? '(required)' : '(optional)'}
        <input
          value={gstin}
          maxLength={20}
          autoCapitalize="characters"
          spellCheck={false}
          placeholder="33ABCDE1234F1Z7"
          aria-invalid={check !== null && !check.ok}
          aria-describedby="gstin-help"
          onChange={(e) => setGstin(e.target.value.toUpperCase())}
        />
      </label>
      <p id="gstin-help" className={check && !check.ok ? 'error' : 'muted'}>
        {check
          ? check.ok
            ? `Valid · registered in ${check.state}`
            : check.reason
          : needsGstin
            ? 'Enter the 15-character GSTIN from your registration certificate.'
            : `State: ${STATES[shop.state_code] ?? shop.state_code}`}
      </p>

      {preview && sample && (
        <div className="preview" aria-live="polite">
          <h2>How a {formatRupees(sample.price_paise)} {sample.name} will print</h2>
          <dl className="sums num">
            <dt>Document</dt>
            <dd>{TYPES.find((t) => t.id === type)?.prints}</dd>
            {type === 'regular' && (
              <>
                <dt>Taxable value</dt>
                <dd>{formatRupees(preview.taxable)}</dd>
                <dt>CGST @{formatRate(sample.gst_rate_bp / 2)}</dt>
                <dd>{formatRupees(preview.cgst)}</dd>
                <dt>SGST @{formatRate(sample.gst_rate_bp / 2)}</dt>
                <dd>{formatRupees(preview.sgst)}</dd>
              </>
            )}
            <dt className="grand">Customer pays</dt>
            <dd className="grand">{formatRupees(preview.total)}</dd>
          </dl>
        </div>
      )}

      {typeChanged && (
        <p className="warn">
          From now on every tablet will print “{TYPES.find((t) => t.id === type)?.prints}”. Bills already printed do not
          change. Tablets switch when they next refresh the menu (on opening or coming online).
        </p>
      )}
      <div className="sheet-actions">
        <button className="primary" disabled={!dirty || blocked || busy} onClick={() => void save()}>
          Save shop settings
        </button>
      </div>
      {saved && !dirty && (
        <p className="ok" role="status">
          Saved.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <MenuPrices />
    </section>
  );
}

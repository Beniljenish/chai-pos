/**
 * The printed bill. The document title follows the shop's GST registration:
 * tax invoice (regular), bill of supply (composition), or plain bill.
 * Printed through the browser's print dialog at 58 mm width (see styles.css).
 */
import { useEffect } from 'react';
import type { LocalBill } from '../lib/db';
import { formatRupees } from '../lib/gst';
import { useSession } from './session';

const TITLES = {
  regular: 'Tax invoice',
  composition: 'Bill of supply',
  unregistered: 'Bill',
} as const;

const PAYMENT_LABELS = { cash: 'Cash', upi: 'UPI', card: 'Card' } as const;

function istDateTime(iso: string) {
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));
}

export function Receipt({ bill, onClose, autoPrint = false }: { bill: LocalBill; onClose(): void; autoPrint?: boolean }) {
  const { catalogue } = useSession();
  const shop = catalogue?.shop;
  const p = bill.payload;
  const gstType = p.gst_type;

  useEffect(() => {
    if (autoPrint && !navigator.webdriver) window.print();
  }, [autoPrint]);

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={`Bill ${bill.invoiceNo}`}>
      <div className="receipt-wrap">
        <article className="receipt">
          <header>
            <strong className="shop-name">{shop?.name}</strong>
            {shop?.address && <span>{shop.address}</span>}
            {gstType === 'regular' && shop?.gstin && <span>GSTIN {shop.gstin}</span>}
            <span className="doc-title">{TITLES[gstType]}</span>
            {gstType === 'composition' && <span>Composition taxable person, not eligible to collect tax</span>}
          </header>
          <dl className="meta">
            <dt>No.</dt>
            <dd>{bill.invoiceNo}</dd>
            <dt>Date</dt>
            <dd>{istDateTime(bill.soldAt)}</dd>
          </dl>
          <table>
            <tbody>
              {p.lines.map((l, i) => (
                <tr key={i}>
                  <td>
                    {l.name}
                    {l.modifiers.length > 0 && <small> ({l.modifiers.map((m) => m.name).join(', ')})</small>}
                    <br />
                    <small className="num">
                      {l.qty} × {formatRupees(l.unit_price_paise + l.modifiers.reduce((a, m) => a + m.price_delta_paise, 0))}
                    </small>
                  </td>
                  <td className="num right">{formatRupees(l.totals.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <dl className="sums num">
            {gstType === 'regular' && p.totals.cgst > 0 && (
              <>
                <dt>Taxable value</dt>
                <dd>{formatRupees(p.totals.taxable)}</dd>
                <dt>CGST</dt>
                <dd>{formatRupees(p.totals.cgst)}</dd>
                <dt>SGST</dt>
                <dd>{formatRupees(p.totals.sgst)}</dd>
              </>
            )}
            {p.totals.round_off !== 0 && (
              <>
                <dt>Round off</dt>
                <dd>{formatRupees(p.totals.round_off)}</dd>
              </>
            )}
            <dt className="grand">Total</dt>
            <dd className="grand">{formatRupees(p.totals.total)}</dd>
            <dt>Paid by</dt>
            <dd>{PAYMENT_LABELS[p.payment_mode]}</dd>
          </dl>
          <footer>Thank you</footer>
        </article>
        <div className="receipt-actions no-print">
          <button onClick={() => window.print()}>Print again</button>
          <button className="primary" onClick={onClose} autoFocus>
            New bill
          </button>
        </div>
      </div>
    </div>
  );
}

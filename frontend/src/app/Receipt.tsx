/**
 * The printed bill. The document title follows the shop's GST registration:
 * tax invoice (regular), bill of supply (composition), or plain bill.
 * Printed through the browser's print dialog at 58 mm width (see styles.css).
 */
import { Fragment, useEffect, useState } from 'react';
import type { LocalBill } from '../lib/db';
import { formatRate, formatRupees, taxByRate } from '../lib/gst';
import { db } from '../lib/db';
import { PAYMENT, paymentRows, receiptRows } from '../lib/escpos';
import { browserEnv, loadPrinter, printRows } from '../lib/printer';
import { PrinterSheet } from './PrinterSettings';
import { useSession } from './session';

const TITLES = {
  regular: 'Tax invoice',
  composition: 'Bill of supply',
  unregistered: 'Bill',
} as const;


function istDateTime(iso: string) {
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));
}

export function Receipt({
  bill,
  onClose,
  autoPrint = false,
  voided = false,
  doneLabel = 'New bill',
}: {
  bill: LocalBill;
  onClose(): void;
  autoPrint?: boolean;
  voided?: boolean;
  doneLabel?: string;
}) {
  const { catalogue } = useSession();
  const shop = catalogue?.shop;
  const p = bill.payload;
  const gstType = p.gst_type;

  const [printError, setPrintError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  async function print(reprint: boolean) {
    if (!shop) return;
    setPrintError(null);
    try {
      const settings = await loadPrinter(db);
      await printRows(receiptRows(bill, shop, settings.width, { voided, reprint }), settings, browserEnv);
    } catch (e) {
      setPrintError(e instanceof Error ? e.message : 'Could not print');
    }
  }

  useEffect(() => {
    if (!autoPrint) return;
    void loadPrinter(db).then((s) => {
      if (s.autoPrint) void print(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPrint]);

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={`Bill ${bill.invoiceNo}`}>
      <div className="receipt-wrap">
        <article className="receipt">
          {voided && <p className="void-stamp">VOIDED: not a valid bill</p>}
          <header>
            <strong className="shop-name">{shop?.name}</strong>
            {shop?.address && <span>{shop.address}</span>}
            {/* Both a tax invoice and a bill of supply must carry the supplier's GSTIN. */}
            {gstType !== 'unregistered' && shop?.gstin && <span>GSTIN {shop.gstin}</span>}
            <span className="doc-title">{TITLES[gstType]}</span>
            {gstType === 'composition' && (
              <span>Composition taxable person, not eligible to collect tax on supplies</span>
            )}
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
                  <td className="num right">{formatRupees(p.totals.discount ? l.totals.gross : l.totals.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <dl className="sums num">
            {Boolean(p.totals.discount) && (
              <>
                <dt>Discount{p.discount_reason ? ` (${p.discount_reason})` : ''}</dt>
                <dd>-{formatRupees(p.totals.discount ?? 0)}</dd>
              </>
            )}
            {gstType === 'regular' && p.totals.cgst > 0 && (
              <>
                <dt>Taxable value</dt>
                <dd>{formatRupees(p.totals.taxable)}</dd>
                {/* The rate must be printed, one row per rate when items differ. */}
                {taxByRate(p.lines).map((g) => (
                  <Fragment key={g.rateBp}>
                    <dt>CGST @{formatRate(g.rateBp / 2)}</dt>
                    <dd>{formatRupees(g.cgst)}</dd>
                    <dt>SGST @{formatRate(g.rateBp / 2)}</dt>
                    <dd>{formatRupees(g.sgst)}</dd>
                  </Fragment>
                ))}
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
            {p.payment_parts?.length ? (
              paymentRows(p).map(([label, paise]) => (
                <Fragment key={label}>
                  <dt>{label}</dt>
                  <dd>{formatRupees(paise)}</dd>
                </Fragment>
              ))
            ) : (
              <>
                <dt>Paid by</dt>
                <dd>{p.payment_mode === 'credit' ? 'Credit (khata)' : PAYMENT[p.payment_mode]}</dd>
              </>
            )}
            {p.customer?.name && (
              <>
                <dt>Customer</dt>
                <dd>{p.customer.name}</dd>
              </>
            )}
          </dl>
          <footer>Thank you</footer>
        </article>
        {printError && (
          <p className="error no-print" role="alert">
            {printError}{' '}
            <button className="quiet" onClick={() => setSettingsOpen(true)}>
              Printer settings
            </button>
          </p>
        )}
        <div className="receipt-actions no-print">
          <button onClick={() => void print(!autoPrint)}>{autoPrint ? 'Print again' : 'Reprint'}</button>
          <button className="primary" onClick={onClose} autoFocus>
            {doneLabel}
          </button>
        </div>
        <button className="quiet no-print printer-link" onClick={() => setSettingsOpen(true)}>
          Printer settings
        </button>
      </div>
      {settingsOpen && <PrinterSheet onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}

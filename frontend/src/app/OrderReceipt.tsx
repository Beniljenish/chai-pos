/**
 * "Save receipt": a plain summary of one order that the customer can print or save as a PDF with
 * the browser's own print dialog (README, "9.21"). It is a record for the customer's own use, not a
 * tax invoice: the outlet's bill is the invoice.
 */
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import type { HistoryRow } from '../lib/publicApi';
import { Sheet } from './Sheet';

const when = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));

export function OrderReceipt({ order, onClose }: { order: HistoryRow; onClose(): void }) {
  return (
    <Sheet title={t('Receipt')} onClose={onClose}>
      <article className="print-receipt" aria-label={t('Receipt')}>
        <h2>{order.outlet}</h2>
        <p className="muted">
          {order.court} · {when(order.placed_at)}
        </p>
        <p>
          {t('Token')} <strong>{order.token}</strong>
        </p>
        <ul>
          {order.items.map((i, n) => (
            <li key={n}>
              {i.qty} × {i.name}
            </li>
          ))}
        </ul>
        {order.discount_paise ? (
          <p>
            {t('Offer {code}', { code: order.coupon_code ?? '' })}: −{formatRupees(order.discount_paise)}
          </p>
        ) : null}
        <p>
          <strong>
            {order.paid_online ? t('Paid online') : t('Total')}: {formatRupees(order.total_paise)}
          </strong>
        </p>
        <p className="muted">{t('This is your own record of the order, not a tax invoice. The outlet’s bill is the invoice.')}</p>
      </article>
      <div className="sheet-actions">
        <button className="primary" onClick={() => window.print()}>
          {t('Print or save as PDF')}
        </button>
        <button onClick={onClose}>{t('Close')}</button>
      </div>
    </Sheet>
  );
}

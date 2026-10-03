import { useEffect, useState } from 'react';
import { businessDate } from '../lib/billing';
import { db, type LocalBill } from '../lib/db';
import { formatRupees } from '../lib/gst';
import { Receipt } from './Receipt';
import { useSession } from './session';

const REASONS: Record<string, string> = {
  device_clock_ahead: "This tablet's clock is wrong. Fix the date and time in settings.",
  bill_too_old: 'This bill is over 30 days old and was not accepted. Tell the owner.',
  invoice_number_already_used: 'This invoice number was already used. Tell the owner.',
  id_reused_with_different_content: 'This bill was changed after saving. Tell the owner.',
  unknown_menu_item: 'An item on this bill was deleted from the menu. Tell the owner.',
};

function explain(reason?: string) {
  if (!reason) return 'Not accepted. Tell the owner.';
  return REASONS[reason] ?? REASONS[reason.split(':')[0]] ?? `Not accepted (${reason}). Tell the owner.`;
}

function timeIST(iso: string) {
  return new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', timeStyle: 'short' }).format(new Date(iso));
}

export function BillsScreen() {
  const { sync } = useSession();
  const [bills, setBills] = useState<LocalBill[]>([]);
  const [open, setOpen] = useState<LocalBill | null>(null);

  // Reload whenever the sync state changes (a bill was sent or rejected).
  useEffect(() => {
    db.bills
      .where('businessDate')
      .equals(businessDate(new Date()))
      .reverse()
      .sortBy('seq')
      .then(setBills);
  }, [sync]);

  const total = bills.reduce((a, b) => a + b.totalPaise, 0);

  return (
    <main className="bills">
      <header className="bills-head">
        <h1>Today on this tablet</h1>
        <p>
          <strong className="num">{formatRupees(total)}</strong> from {bills.length} bill
          {bills.length === 1 ? '' : 's'}
        </p>
      </header>
      {bills.length === 0 ? (
        <p className="empty">No bills yet today.</p>
      ) : (
        <ul className="bill-list">
          {bills.map((b) => (
            <li key={b.id}>
              <button onClick={() => setOpen(b)}>
                <span className="num">{b.invoiceNo}</span>
                <span className="muted">{timeIST(b.soldAt)}</span>
                <span className="num right">{formatRupees(b.totalPaise)}</span>
                <span className={`status ${b.status}`}>
                  {b.status === 'synced' ? 'Sent' : b.status === 'pending' ? 'Waiting' : 'Problem'}
                </span>
              </button>
              {b.status === 'rejected' && <p className="error">{explain(b.reason)}</p>}
            </li>
          ))}
        </ul>
      )}
      {open && <Receipt bill={open} onClose={() => setOpen(null)} />}
    </main>
  );
}

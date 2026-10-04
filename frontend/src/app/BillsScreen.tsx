import { useEffect, useState } from 'react';
import { businessDate } from '../lib/billing';
import { db, type LocalBill } from '../lib/db';
import { formatRupees } from '../lib/gst';
import type { ServerBill } from '../lib/types';
import { api } from './apiClient';
import { PrinterSheet } from './PrinterSettings';
import { CustomersSheet } from './CustomersUI';
import { Receipt } from './Receipt';
import { ShiftPanel } from './ShiftUI';
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
  const [printer, setPrinter] = useState(false);
  const [customers, setCustomers] = useState(false);
  // Voids happen on the server (owner only). Shown when online; offline, the list
  // is what this tablet printed.
  const [voided, setVoided] = useState<Set<string>>(new Set());

  // Reload whenever the sync state changes (a bill was sent or rejected).
  useEffect(() => {
    db.bills
      .where('businessDate')
      .equals(businessDate(new Date()))
      .reverse()
      .sortBy('seq')
      .then(setBills);
    api
      .get<ServerBill[]>('/bills')
      .then((server) => setVoided(new Set(server.filter((b) => b.status === 'void').map((b) => b.id))))
      .catch(() => {}); // offline or signed out: keep what we knew
  }, [sync]);

  const live = bills.filter((b) => !voided.has(b.id));
  const total = live.reduce((a, b) => a + b.totalPaise, 0);

  return (
    <main className="bills">
      <header className="bills-head">
        <div className="manage-head">
          <h1>Today on this tablet</h1>
          <span className="head-actions">
            <button className="quiet" onClick={() => setCustomers(true)}>
              Customers
            </button>
            <button className="quiet" onClick={() => setPrinter(true)}>
              Printer
            </button>
          </span>
        </div>
        <p>
          <strong className="num">{formatRupees(total)}</strong> from {live.length} bill
          {live.length === 1 ? '' : 's'}
          {bills.length > live.length && <span className="muted"> ({bills.length - live.length} voided)</span>}
        </p>
      </header>
      <ShiftPanel />
      {bills.length === 0 ? (
        <p className="empty">No bills yet today.</p>
      ) : (
        <ul className="bill-list">
          {bills.map((b) => (
            <li key={b.id}>
              <button onClick={() => setOpen(b)}>
                <span className="num">{b.invoiceNo}</span>
                <span className="muted">{timeIST(b.soldAt)}</span>
                <span className={`num right ${voided.has(b.id) ? 'struck' : ''}`}>{formatRupees(b.totalPaise)}</span>
                {voided.has(b.id) ? (
                  <span className="status voided">Voided</span>
                ) : (
                  <span className={`status ${b.status}`}>
                    {b.status === 'synced' ? 'Sent' : b.status === 'pending' ? 'Waiting' : 'Problem'}
                  </span>
                )}
              </button>
              {b.status === 'rejected' && <p className="error">{explain(b.reason)}</p>}
            </li>
          ))}
        </ul>
      )}
      {printer && <PrinterSheet onClose={() => setPrinter(false)} />}
      {customers && <CustomersSheet onClose={() => setCustomers(false)} />}
      {open && <Receipt bill={open} voided={voided.has(open.id)} onClose={() => setOpen(null)} />}
    </main>
  );
}

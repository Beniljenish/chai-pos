/**
 * Collect a saved bill's payment through Razorpay (README, "Phase 8a"). The bill
 * already exists; this only records whether the customer's money arrived. If
 * anything goes wrong, the cashier takes the money another way and the owner
 * sees the bill as "not paid online" in the sales report.
 */
import { useCallback, useEffect, useState } from 'react';
import type { LocalBill } from '../lib/db';
import { db } from '../lib/db';
import { formatRupees } from '../lib/gst';
import {
  checkoutUrl,
  explainOnline,
  healthWords,
  type RazorpayHealth,
  onlineStatus,
  orderFor,
  type OnlineMethod,
  type OnlineOrder,
  type OnlineState,
} from '../lib/payments';
import { api } from './apiClient';
import { useSession } from './session';
import { Sheet } from './Sheet';

const POLL_MS = 2000;

export function OnlinePayment({ bill, method, onDone }: { bill: LocalBill; method: OnlineMethod; onDone(): void }) {
  const { worker } = useSession();
  const [order, setOrder] = useState<OnlineOrder | null>(null);
  const [state, setState] = useState<OnlineState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Send the bill now and wait (up to ~10 s) until it is on the server.
  const syncNow = useCallback(async () => {
    await worker?.kick();
    for (let i = 0; i < 20; i++) {
      if ((await db.bills.get(bill.id))?.status === 'synced') return;
      await new Promise((r) => setTimeout(r, 500));
      void worker?.kick();
    }
  }, [bill.id, worker]);

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setOrder(await orderFor(api, syncNow, bill.id, method));
    } catch (e) {
      setError(explainOnline(e));
    } finally {
      setBusy(false);
    }
  }, [bill.id, method, syncNow]);

  useEffect(() => {
    void start();
  }, [start]);

  // Watch the payment on the server while the customer pays in the other tab.
  useEffect(() => {
    if (!order || state?.status === 'paid') return;
    const t = setInterval(() => {
      onlineStatus(api, order.razorpay_order_id).then(setState, () => undefined);
    }, POLL_MS);
    return () => clearInterval(t);
  }, [order, state?.status]);

  const paid = state?.status === 'paid';
  const amount = formatRupees(order?.amount_paise ?? bill.totalPaise);
  const open = () => order && window.open(checkoutUrl(api.baseUrl, order.razorpay_order_id), '_blank', 'noopener');

  return (
    <Sheet title={paid ? 'Paid' : `Collect ${amount} online`} onClose={onDone}>
      <p className="muted">
        Bill <span className="num">{bill.invoiceNo}</span> is saved. {method === 'upi' ? 'UPI' : 'Card'} through Razorpay
        (test mode).
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {paid ? (
        <p className="ok" role="status">
          Payment received: {formatRupees(state.paid_paise ?? 0)}.
        </p>
      ) : (
        order && (
          <>
            <p role="status">
              {state?.status === 'failed'
                ? `Not paid: ${state.error}. The customer can try again.`
                : 'Open the payment page and let the customer pay there (UPI app or card).'}
            </p>
            <div className="sheet-actions">
              <button className="primary" onClick={open}>
                Open payment page
              </button>
            </div>
          </>
        )
      )}
      <div className="sheet-actions">
        {paid ? (
          <button className="primary" onClick={onDone}>
            Print receipt
          </button>
        ) : (
          <>
            {error && (
              <button onClick={() => void start()} disabled={busy}>
                Try again
              </button>
            )}
            <button onClick={onDone}>Took the payment another way</button>
          </>
        )}
      </div>
      {busy && <p className="muted">Sending the bill and asking Razorpay…</p>}
    </Sheet>
  );
}

/** Owner, Shop & GST: is Razorpay set up, test or live, and do the keys work? */
export function RazorpaySettings() {
  const [h, setH] = useState<RazorpayHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const check = useCallback(async () => {
    setBusy(true);
    try {
      setH(await api.get<RazorpayHealth>('/payments/razorpay/health'));
      setError(null);
    } catch (e) {
      setError(explainOnline(e));
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void check();
  }, [check]);
  const words = h ? healthWords(h) : null;
  return (
    <section aria-labelledby="rzp-title">
      <h2 id="rzp-title">Online payments (Razorpay)</h2>
      {words && (
        <p className={words.ok ? 'ok' : 'warn'} role="status">
          {words.text}
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <p className="muted">
        At the till, pick UPI or Card and tick &quot;Collect through Razorpay&quot;. The payment page shows only the method
        chosen; the till marks the bill paid once Razorpay confirms it.
      </p>
      <button disabled={busy} onClick={() => void check()}>
        {busy ? 'Checking…' : 'Check connection'}
      </button>
    </section>
  );
}

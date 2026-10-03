/**
 * The kitchen screen (README, "Kitchen screen"): every KOT still to be made,
 * oldest first. Tap an item when it is ready, or "All ready" for the ticket.
 * Waiters see "Ready" on the order. A tablet in the kitchen stays on this view.
 */
import { useState } from 'react';
import { db } from '../lib/db';
import { act, type LiveOrder } from '../lib/orders';
import { KITCHEN_LATE_MIN, kitchenTickets } from '../lib/table';
import type { Catalogue } from '../lib/types';
import { useSession } from './session';

export function KitchenView({
  catalogue,
  orders,
  now,
  reload,
}: {
  catalogue: Catalogue;
  orders: LiveOrder[];
  now: number;
  reload(): Promise<void>;
}) {
  const { user, worker } = useSession();
  const [busy, setBusy] = useState(false);
  const tickets = kitchenTickets(catalogue, orders, now);

  async function ready(orderId: string, lineIds: string[]) {
    if (!user || busy) return;
    setBusy(true);
    try {
      await act(db, orderId, 'ready', { line_ids: lineIds }, user.id);
      await reload();
      void worker?.kick();
    } finally {
      setBusy(false);
    }
  }

  if (tickets.length === 0) {
    return (
      <div className="empty-card kitchen-empty">
        <p>
          <strong>Nothing to make.</strong> New kitchen tickets appear here within a few seconds of being sent.
        </p>
      </div>
    );
  }

  return (
    <ul className="kitchen-grid" aria-label="Kitchen tickets">
      {tickets.map((t) => (
        <li key={`${t.orderId}:${t.kotNo}`} className={`kitchen-ticket ${t.minutes >= KITCHEN_LATE_MIN ? 'late' : ''}`}>
          <header>
            <strong className="kitchen-label">{t.label}</strong>
            <span className="num">{t.minutes} min</span>
          </header>
          <p className="muted kitchen-kot">
            KOT {t.kotNo}
            {t.orderType !== 'dine_in' ? ` · ${t.orderType === 'takeaway' ? 'Takeaway: pack it' : 'Delivery: pack it'}` : ''}
          </p>
          <ul className="kitchen-lines">
            {t.lines.map((l) => (
              <li key={l.line_id}>
                <button onClick={() => void ready(t.orderId, [l.line_id])} aria-label={`${l.name} ready`} disabled={busy}>
                  <span className="kitchen-qty num">{l.qty}</span>
                  <span>
                    {l.name}
                    {l.modifiers.length > 0 && <span className="kitchen-mods">{l.modifiers.join(', ')}</span>}
                    {l.note && <span className="kitchen-note">{l.note}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              void ready(
                t.orderId,
                t.lines.map((l) => l.line_id),
              )
            }
          >
            All ready
          </button>
        </li>
      ))}
    </ul>
  );
}

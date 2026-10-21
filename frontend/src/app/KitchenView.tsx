/**
 * The kitchen screen (README, "Kitchen screen"): every KOT still to be made,
 * oldest first. Tap an item when it is ready, or "All ready" for the ticket.
 * Waiters see "Ready" on the order. A tablet in the kitchen stays on this view.
 */
import { useState } from 'react';
import { db } from '../lib/db';
import { act, type LiveOrder } from '../lib/orders';
import { announce } from '../lib/announce';
import { KITCHEN_LATE_MIN, kitchenTickets, onlineToken } from '../lib/table';
import type { Catalogue } from '../lib/types';
import { useSession } from './session';
import { t, useLang } from '../lib/i18n';

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
  useLang();
  const { user, worker } = useSession();
  const [busy, setBusy] = useState(false);
  const tickets = kitchenTickets(catalogue, orders, now);

  async function ready(orderId: string, lineIds: string[]) {
    if (!user || busy) return;
    setBusy(true);
    try {
      await act(db, orderId, 'ready', { line_ids: lineIds }, user.id);
      // A customer's online order has a token: say it, for people who are not looking at the screen.
      const order = orders.find((o) => o.id === orderId);
      const token = order ? onlineToken(order.state) : null;
      if (token) announce('ready', { token });
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
          <strong>{t("Nothing to make.")}</strong> {t("New kitchen tickets appear here within a few seconds of being sent.")}
        </p>
      </div>
    );
  }

  return (
    <ul className="kitchen-grid" aria-label={t("Kitchen tickets")}>
      {tickets.map((tk) => (
        <li key={`${tk.orderId}:${tk.kotNo}`} className={`kitchen-ticket ${tk.minutes >= KITCHEN_LATE_MIN ? 'late' : ''}`}>
          <header>
            <strong className="kitchen-label">{tk.label}</strong>
            <span className="num">{tk.minutes} {t("min")}</span>
          </header>
          <p className="muted kitchen-kot">
            {t("KOT")} {tk.kotNo}
            {tk.orderType !== 'dine_in' ? ` · ${tk.orderType === 'takeaway' ? t("Takeaway: pack it") : t("Delivery: pack it")}` : ''}
          </p>
          <ul className="kitchen-lines">
            {tk.lines.map((l) => (
              <li key={l.line_id}>
                <button onClick={() => void ready(tk.orderId, [l.line_id])} aria-label={t('{name} ready', { name: l.name })} disabled={busy}>
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
                tk.orderId,
                tk.lines.map((l) => l.line_id),
              )
            }
          >
            {t("All ready")}
          </button>
        </li>
      ))}
    </ul>
  );
}

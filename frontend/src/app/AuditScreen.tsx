/** The change log (README, "9.21"): who changed a price, recipe, offer, person or GST setting. */
import { Hint } from './Hint';
import { useEffect, useState } from 'react';
import { formatRupees } from '../lib/gst';
import { t } from '../lib/i18n';
import { api } from './apiClient';
import { explainError } from './errors';
import { Loading } from './Status';

interface Event {
  id: string;
  at: string;
  who: string;
  action: string;
  subject: string;
  detail: Record<string, unknown>;
}

const when = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true }).format(
    new Date(iso),
  );

/** One line in plain words. Unknown actions fall back to the raw name, never to nothing. */
export function describe(e: Event): string {
  const d = e.detail;
  switch (e.action) {
    case 'menu_changed': {
      const money = d.field === 'price_paise';
      const show = (v: unknown) => (money ? formatRupees(Number(v)) : String(v));
      return t('{item}: {field} {before} → {after}', {
        item: e.subject,
        field: money ? t('price') : String(d.field),
        before: show(d.before),
        after: show(d.after),
      });
    }
    case 'menu_added':
      return t('Added to the menu: {item}', { item: e.subject });
    case 'recipe_changed':
      return t('Recipe changed: {item}', { item: e.subject });
    case 'offer_made':
      return t('Offer made: {code}', { code: e.subject });
    case 'offer_changed':
      return t('Offer changed: {code}', { code: e.subject });
    case 'person_added':
      return t('Person added: {name}', { name: e.subject });
    case 'person_switched_off':
      return t('Switched off: {name}', { name: e.subject });
    case 'person_switched_on':
      return t('Switched on: {name}', { name: e.subject });
    case 'password_reset':
      return t('Password reset for {name}', { name: e.subject });
    case 'pay_rate_changed':
      return t('Hourly rate changed for {name}', { name: e.subject });
    case 'shop_changed':
      return t('Shop setting changed: {field}', { field: e.subject });
    case 'attendance_corrected':
      return t('A clock-in/out entry was corrected');
    default:
      return `${e.action}: ${e.subject}`;
  }
}

export function AuditScreen() {
  const [events, setEvents] = useState<Event[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<{ events: Event[] }>('/audit?days=60').then((r) => setEvents(r.events), (e) => setError(explainError(e)));
  }, []);
  return (
    <section className="audit">
      <header className="manage-head">
        <h1>{t('Changes')}</h1>
      </header>
      <Hint>{t('Who changed prices, recipes, offers, people and GST settings in the last 60 days. It can only grow: nobody can edit or delete a line.')}</Hint>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!events && !error && <Loading />}
      {events && events.length === 0 && <p className="muted">{t('Nothing changed yet.')}</p>}
      {events && events.length > 0 && (
        <ul className="sop-list" aria-label={t('Changes')}>
          {events.map((e) => (
            <li key={e.id}>
              <span>
                {describe(e)}
                <br />
                <span className="muted">
                  {e.who} · {when(e.at)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

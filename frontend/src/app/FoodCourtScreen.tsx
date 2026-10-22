/**
 * Owner: this shop's place in a food court. The owner sees the court and its QR and
 * switches their own outlet's "taking online orders" on and off. Making courts and
 * adding or removing outlets is the super admin's (/admin), not the owner's (README, "9.12").
 */
import { useCallback, useEffect, useState } from 'react';
import { boardPath, courtPath, isPaused } from '../lib/foodcourt';
import { getLang, t } from '../lib/i18n';
import { slotLabel, tableLink } from '../lib/pickup';
import { formatRupees } from '../lib/gst';
import type { FoodCourtView } from '../lib/types';
import { api } from './apiClient';
import { explainError } from './errors';
import { Qr } from './Qr';
import { StatementPanel } from './StatementPanel';
import type { Statement } from '../lib/statement';
import { Loading, LoadError } from './Status';
import { useSession } from './session';

interface Summary {
  enough: boolean;
  comments: number;
  needed?: number;
  summary?: string;
  themes?: { theme: string; mentions: number; mood: 'good' | 'bad' | 'mixed' }[];
}

/** "What customers say": a few lines from the written comments of the last four weeks. */
function FeedbackSummary() {
  const [s, setS] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      setS(await api.post<Summary>(`/ai/feedback-summary?lang=${getLang()}`, {}));
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="fc-feedback">
      <button disabled={busy} onClick={() => void run()}>
        ✨ {t('What customers say')}
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {s && !s.enough && (
        <p className="muted">{t('Needs at least {n} written comments in the last 4 weeks; there are {have}.', { n: s.needed ?? 5, have: s.comments })}</p>
      )}
      {s?.enough && (
        <>
          <p>{s.summary}</p>
          <ul>
            {(s.themes ?? []).map((th) => (
              <li key={th.theme}>
                <span aria-hidden="true">{th.mood === 'good' ? '👍' : th.mood === 'bad' ? '👎' : '↔'}</span> {th.theme}{' '}
                <span className="muted">({t('{n} mentions', { n: th.mentions })})</span>
              </li>
            ))}
          </ul>
          <p className="muted">{t('Written by the AI from your customers’ comments. Read the comments too.')}</p>
        </>
      )}
    </div>
  );
}

export function FoodCourtScreen() {
  const [v, setV] = useState<FoodCourtView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { catalogue } = useSession();

  const load = useCallback(async () => {
    try {
      setV(await api.get<FoodCourtView>('/food-court'));
      setError(null);
    } catch (e) {
      setError(explainError(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function setPrep(minutes: number) {
    setBusy(true);
    setError(null);
    try {
      setV(await api.patch<FoodCourtView>('/food-court/me', { prep_minutes: Math.max(0, Math.min(180, minutes)) }));
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function setPickup(body: {
    pickup_enabled?: boolean;
    pickup_capacity?: number;
    busy_pause_on?: boolean;
    busy_limit?: number;
    resume_now?: boolean;
    loyalty_every?: number;
    loyalty_reward_paise?: number;
  }) {
    setBusy(true);
    setError(null);
    try {
      setV(await api.patch<FoodCourtView>('/food-court/me', body));
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      setV(await api.patch<FoodCourtView>('/food-court/me', { accepting_orders: !v?.accepting_orders }));
    } catch (e) {
      setError(explainError(e));
    } finally {
      setBusy(false);
    }
  }

  const court = v?.court ?? null;
  const myOutletId = v?.outlets?.find((o) => o.is_me)?.id ?? null;
  const tables = (catalogue?.areas ?? []).filter((a) => a.is_active).flatMap((a) => a.tables.filter((x) => x.is_active).map((x) => x.name));
  const link = court ? `${window.location.origin}${courtPath(court.slug)}` : '';

  return (
    <section className="foodcourt">
      <header className="manage-head">
        <h1>Food court</h1>
      </header>
      {error && <LoadError error={error} onRetry={() => void load()} />}
      {v === null ? (
        !error && <Loading />
      ) : court === null ? (
        <p className="muted">
          Your outlet is not in a food court. A food court&apos;s administrator adds outlets: ask them to add you, with
          this number as the owner&apos;s.
        </p>
      ) : (
        <>
          <p className="muted">{court.name}</p>

          <div className="panel-inline fc-switch">
            <div>
              <strong>Taking online orders</strong>
              <p className="muted">
                {v.accepting_orders
                  ? 'Customers can order from your outlet. New orders appear on your Tables screen.'
                  : 'Customers see your outlet as closed.'}
              </p>
            </div>
            <button
              role="switch"
              aria-checked={Boolean(v.accepting_orders)}
              aria-label="Taking online orders"
              className={`fc-toggle ${v.accepting_orders ? 'on' : ''}`}
              disabled={busy}
              onClick={() => void toggle()}
            >
              <span />
            </button>
          </div>

          <div className="panel-inline fc-switch">
            <div>
              <strong>Usual wait</strong>
              <p className="muted">
                {v.prep_minutes
                  ? `Customers are told "usually ready in about ${v.prep_minutes} min".`
                  : 'Customers are not told a wait. Set one so they know what to expect.'}
              </p>
            </div>
            <span className="fc-stepper" role="group" aria-label="Usual wait in minutes">
              <button disabled={busy || !v.prep_minutes} aria-label="5 minutes less" onClick={() => void setPrep((v.prep_minutes ?? 0) - 5)}>
                −
              </button>
              <strong className="num">{v.prep_minutes ? `${v.prep_minutes} min` : 'not set'}</strong>
              <button disabled={busy} aria-label="5 minutes more" onClick={() => void setPrep((v.prep_minutes ?? 0) + 5)}>
                +
              </button>
            </span>
          </div>

          <div className="panel-inline fc-switch">
            <div>
              <strong>{t('Pickup times')}</strong>
              <p className="muted">
                {v.pickup_enabled
                  ? t('Customers can choose a time, 15 minutes apart. Your kitchen sees an order from 15 minutes before its time.')
                  : t('Customers can only order for now.')}
              </p>
            </div>
            <button
              role="switch"
              aria-checked={Boolean(v.pickup_enabled)}
              aria-label={t('Pickup times')}
              className={`fc-toggle ${v.pickup_enabled ? 'on' : ''}`}
              disabled={busy}
              onClick={() => void setPickup({ pickup_enabled: !v.pickup_enabled })}
            >
              <span />
            </button>
          </div>
          {v.pickup_enabled && (
            <div className="panel-inline fc-switch">
              <div>
                <strong>{t('Orders per time slot')}</strong>
                <p className="muted">{t('Pause a busy slot by lowering this.')}</p>
              </div>
              <span className="fc-stepper" role="group" aria-label={t('Orders per time slot')}>
                <button
                  disabled={busy || (v.pickup_capacity ?? 5) <= 1}
                  aria-label={t('One less')}
                  onClick={() => void setPickup({ pickup_capacity: (v.pickup_capacity ?? 5) - 1 })}
                >
                  −
                </button>
                <strong className="num">{v.pickup_capacity ?? 5}</strong>
                <button
                  disabled={busy || (v.pickup_capacity ?? 5) >= 60}
                  aria-label={t('One more')}
                  onClick={() => void setPickup({ pickup_capacity: (v.pickup_capacity ?? 5) + 1 })}
                >
                  +
                </button>
              </span>
            </div>
          )}

          <div className="panel-inline fc-switch">
            <div>
              <strong>{t('Pause when busy')}</strong>
              <p className="muted">
                {t('When this many online orders are open, new ones pause for 10 minutes by themselves and customers see when you are back.')}
              </p>
            </div>
            <button
              role="switch"
              aria-checked={Boolean(v.busy_pause_on)}
              aria-label={t('Pause when busy')}
              className={`fc-toggle ${v.busy_pause_on ? 'on' : ''}`}
              disabled={busy}
              onClick={() => void setPickup({ busy_pause_on: !v.busy_pause_on })}
            >
              <span />
            </button>
          </div>
          {v.busy_pause_on && (
            <div className="panel-inline fc-switch">
              <div>
                <strong>{t('Open orders that pause it')}</strong>
              </div>
              <span className="fc-stepper" role="group" aria-label={t('Open orders that pause it')}>
                <button
                  disabled={busy || (v.busy_limit ?? 12) <= 2}
                  aria-label={t('One less')}
                  onClick={() => void setPickup({ busy_limit: (v.busy_limit ?? 12) - 1 })}
                >
                  −
                </button>
                <strong className="num">{v.busy_limit ?? 12}</strong>
                <button
                  disabled={busy || (v.busy_limit ?? 12) >= 40}
                  aria-label={t('One more')}
                  onClick={() => void setPickup({ busy_limit: (v.busy_limit ?? 12) + 1 })}
                >
                  +
                </button>
              </span>
            </div>
          )}
          <div className="panel-inline fc-switch">
            <div>
              <strong>{t('Loyalty reward')}</strong>
              <p className="muted">
                {v.loyalty_every && v.loyalty_reward_paise
                  ? t('Every {n}th order earns {amount} off the next one, for 30 days.', {
                      n: v.loyalty_every,
                      amount: formatRupees(v.loyalty_reward_paise),
                    })
                  : t('Off. Turn it on to thank customers who keep coming back.')}
              </p>
            </div>
            <span className="fc-stepper" role="group" aria-label={t('Orders to earn a reward')}>
              <button
                disabled={busy || !v.loyalty_every}
                aria-label={t('One less')}
                onClick={() => {
                  const n = (v.loyalty_every ?? 0) - 1;
                  void setPickup(n <= 0 ? { loyalty_every: 0, loyalty_reward_paise: 0 } : { loyalty_every: n, loyalty_reward_paise: v.loyalty_reward_paise ?? 1000 });
                }}
              >
                −
              </button>
              <strong className="num">{v.loyalty_every ?? 0}</strong>
              <button
                disabled={busy || (v.loyalty_every ?? 0) >= 50}
                aria-label={t('One more')}
                onClick={() =>
                  void setPickup({ loyalty_every: (v.loyalty_every ?? 4) + (v.loyalty_every ? 1 : 0), loyalty_reward_paise: v.loyalty_reward_paise ?? 1000 })
                }
              >
                +
              </button>
            </span>
          </div>
          {v.loyalty_every && v.loyalty_reward_paise ? (
            <div className="panel-inline fc-switch">
              <div>
                <strong>{t('Reward amount')}</strong>
              </div>
              <span className="fc-stepper" role="group" aria-label={t('Reward amount')}>
                <button
                  disabled={busy || v.loyalty_reward_paise <= 1000}
                  aria-label={t('One less')}
                  onClick={() => void setPickup({ loyalty_every: v.loyalty_every ?? 0, loyalty_reward_paise: v.loyalty_reward_paise! - 1000 })}
                >
                  −
                </button>
                <strong className="num">{formatRupees(v.loyalty_reward_paise)}</strong>
                <button
                  disabled={busy || v.loyalty_reward_paise >= 100000}
                  aria-label={t('One more')}
                  onClick={() => void setPickup({ loyalty_every: v.loyalty_every ?? 0, loyalty_reward_paise: v.loyalty_reward_paise! + 1000 })}
                >
                  +
                </button>
              </span>
            </div>
          ) : null}
          {isPaused(v) && v.paused_until && (
            <div className="panel-inline" role="status">
              <strong>{t('Paused until {time}', { time: slotLabel(v.paused_until) })}</strong>
              <p className="muted">{t('Too many open orders. It opens by itself.')}</p>
              <button disabled={busy} onClick={() => void setPickup({ resume_now: true })}>
                {t('Open now')}
              </button>
            </div>
          )}

          {v.ratings && v.ratings.count > 0 && (
            <section className="panel-inline fc-ratings" aria-label="Ratings">
              <h2>
                {v.ratings.average} ★ <span className="muted">from {v.ratings.count} rating{v.ratings.count === 1 ? '' : 's'}</span>
              </h2>
              <FeedbackSummary />
              <ul>
                {v.ratings.recent
                  .filter((r) => r.comment)
                  .slice(0, 5)
                  .map((r) => (
                    <li key={r.at}>
                      <span aria-label={`${r.rating} stars`}>{'★'.repeat(r.rating)}</span> “{r.comment}” <span className="muted">· {r.name}</span>
                    </li>
                  ))}
              </ul>
            </section>
          )}

          {v.online_money && v.online_money.orders + v.online_money.settled_paise > 0 && (
            <section className="panel-inline fc-money" aria-label="Online payments">
              <h2>Online payments</h2>
              <p className="muted">Customers paid the food court for your orders. It pays you afterwards.</p>
              <dl>
                <div>
                  <dt>Paid by customers ({v.online_money.orders} order{v.online_money.orders === 1 ? '' : 's'})</dt>
                  <dd className="num">{formatRupees(v.online_money.paid_paise)}</dd>
                </div>
                <div>
                  <dt>Already paid to you</dt>
                  <dd className="num">{formatRupees(v.online_money.settled_paise)}</dd>
                </div>
                <div className="fc-owed">
                  <dt>Still due to you</dt>
                  <dd className="num">{formatRupees(v.online_money.owed_paise)}</dd>
                </div>
              </dl>
            </section>
          )}

          {v.online_money && v.online_money.orders > 0 && (
            <StatementPanel
              title="Statement"
              load={(from, to) => api.get<Statement>(`/food-court/statement?from=${from}&to=${to}`)}
            />
          )}

          <section className="fc-qr-card" aria-label="QR code to print">
            <Qr text={link} />
            <strong>{court.name}</strong>
            <span className="muted">Scan to order</span>
            <code>{link}</code>
          </section>
          <button className="quiet" onClick={() => window.print()}>
            Print the QR
          </button>

          <section className="panel-inline" aria-label={t('Display board')}>
            <h2>{t('Display board')}</h2>
            <p className="muted">{t('Open this link on a TV or tablet at the food court. It shows ready tokens, big, and says them aloud once sound is switched on.')}</p>
            <code>{`${window.location.origin}${boardPath(court.slug)}`}</code>
          </section>

          {myOutletId && tables.length > 0 && (
            <section className="panel-inline fc-tables" aria-label={t('Table QR codes')}>
              <h2>{t('Table QR codes')}</h2>
              <p className="muted">{t('Stick one on each table. A customer who scans it orders from your menu and the order says which table to bring it to.')}</p>
              <ul className="fc-table-qrs">
                {tables.map((name) => (
                  <li key={name}>
                    <Qr text={tableLink(window.location.origin, court.slug, myOutletId, name)} label={`QR code for ${name}`} />
                    <strong>{name}</strong>
                  </li>
                ))}
              </ul>
              <button className="quiet" onClick={() => window.print()}>
                {t('Print the table QR codes')}
              </button>
            </section>
          )}

          <h2>Outlets in this food court</h2>
          <ul className="sop-list">
            {(v.outlets ?? []).map((o) => (
              <li key={o.id} className="fc-outlet">
                <span>
                  <strong>{o.name}</strong>
                  {o.is_me && <span className="muted"> · you</span>}
                  <br />
                  <span className="muted">{o.accepting_orders ? 'Taking orders' : 'Not taking orders'}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="muted">To join or leave a food court, ask its administrator.</p>
        </>
      )}
    </section>
  );
}

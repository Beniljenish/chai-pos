/**
 * Order together (README, "9.21"): friends join by link, each adds their own dishes, and the host
 * brings everyone's dishes into their cart and pays once. The shared list holds ids and
 * quantities only; prices and availability are looked up fresh when the host imports it.
 * It polls every few seconds (no live socket: a food court's wifi is not worth a promise of live).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Carts } from '../lib/foodcourt';
import { groupFromSearch, groupLink, linesOf, signature, withOthers } from '../lib/group';
import { dishName, t } from '../lib/i18n';
import { PublicError, publicApi, type GroupState, type PublicMenu } from '../lib/publicApi';

const key = (slug: string) => `taptallow-group:${slug}`;
const POLL_MS = 4000;

function recall(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}
function store(k: string, v: string | null) {
  try {
    if (v === null) localStorage.removeItem(k);
    else localStorage.setItem(k, v);
  } catch {
    /* the group is just not remembered on a reload */
  }
}

export function GroupBar({
  slug,
  token,
  carts,
  menus,
  loadMenu,
  onMerge,
}: {
  slug: string;
  token: string;
  carts: Carts;
  menus: Record<string, PublicMenu>;
  loadMenu(outletId: string): Promise<boolean>;
  /** The host's carts with everyone's dishes in, ready for the cart screen. */
  onMerge(next: Carts): void;
}) {
  const [group, setGroup] = useState<string | null>(() => groupFromSearch(window.location.search) ?? recall(key(slug)));
  const [state, setState] = useState<GroupState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const sent = useRef<string>('');

  const forget = useCallback(() => {
    store(key(slug), null);
    setGroup(null);
    setState(null);
    sent.current = '';
  }, [slug]);

  // A link opened with ?group= joins it; then keep looking at it.
  useEffect(() => {
    if (!group) return;
    let live = true;
    const fromLink = groupFromSearch(window.location.search) === group && recall(key(slug)) !== group;
    const look = () =>
      publicApi.groupState(token, group).then(
        (s) => live && (setState(s), setError(null)),
        (e) => {
          if (!live) return;
          if (e instanceof PublicError && (e.status === 404 || e.status === 403)) {
            setError(t('This group is not open any more.'));
            forget();
          }
        },
      );
    const first = fromLink
      ? publicApi.groupJoin(token, group).then(
          (s) => {
            if (!live) return;
            store(key(slug), group);
            setState(s);
          },
          (e) => {
            if (!live) return;
            setError(e instanceof PublicError && e.status === 409 ? (e.message || t('This group is full.')) : t('This group is not open any more.'));
            forget();
          },
        )
      : look();
    void first;
    const timer = window.setInterval(() => void look(), POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [group, token, slug, forget]);

  // My dishes go to the group whenever they change (only while it is open).
  useEffect(() => {
    if (!group || !state || state.status !== 'open') return;
    const lines = linesOf(carts);
    const sig = signature(lines);
    if (sig === sent.current) return;
    const timer = window.setTimeout(() => {
      sent.current = sig;
      publicApi.groupLines(token, group, lines).then(setState, () => {
        sent.current = ''; // try again at the next change
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [carts, group, state, token]);

  // Names of other people's dishes need those outlets' menus.
  const outletsNeeded = [...new Set((state?.lines ?? []).map((l) => l.outlet_id))].filter((id) => !menus[id]);
  useEffect(() => {
    outletsNeeded.forEach((id) => void loadMenu(id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outletsNeeded.join(',')]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const s = await publicApi.groupCreate(token, slug);
      store(key(slug), s.token);
      sent.current = '';
      setGroup(s.token);
      setState(s);
    } catch (e) {
      setError(e instanceof PublicError && e.status === 429 ? e.message : t('Could not start a group. Please try again.'));
    } finally {
      setBusy(false);
    }
  }

  async function share() {
    if (!state) return;
    const link = groupLink(window.location.origin, slug, state.token);
    try {
      if (navigator.share) await navigator.share({ title: t('Order together'), url: link });
      else {
        await navigator.clipboard.writeText(link);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2500);
      }
    } catch {
      /* cancelled, or the browser has neither: the link is shown below anyway */
    }
  }

  async function payForAll() {
    if (!state || !group) return;
    setBusy(true);
    try {
      const closed = await publicApi.groupClose(token, group);
      setState(closed);
      onMerge(withOthers(carts, closed));
      forget();
    } catch {
      setError(t('Could not do that. Please try again.'));
    } finally {
      setBusy(false);
    }
  }

  if (!group || !state) {
    return (
      <section className="cx-group-bar">
        {error && (
          <p className="cx-note" role="status">
            {error}
          </p>
        )}
        <button disabled={busy} onClick={() => void start()}>
          👥 {t('Order together')}
        </button>
      </section>
    );
  }

  const nameOf = (outlet: string, item: string) => {
    const found = menus[outlet]?.items.find((i) => i.id === item);
    return found ? dishName(found) : t('a dish');
  };
  const others = state.lines.filter((l) => !l.mine);
  return (
    <section className="cx-group-bar panel-inline" aria-label={t('Order together')}>
      <h2>
        👥 {t('Order together')} · {state.members.length === 1 ? t('1 person') : t('{n} people', { n: state.members.length })}
      </h2>
      <ul className="cx-group-members">
        {state.members.map((m) => {
          const theirs = state.lines.filter((l) => l.member === m.name && !l.mine);
          return (
            <li key={m.name + String(m.is_me)}>
              <strong>
                {m.name}
                {m.is_host && ` (${t('host')})`}
                {m.is_me && ` · ${t('you')}`}
              </strong>
              {!m.is_me &&
                (theirs.length === 0 ? (
                  <span className="muted"> {t('choosing…')}</span>
                ) : (
                  <ul>
                    {theirs.map((l, i) => (
                      <li key={i}>
                        {l.qty} × {nameOf(l.outlet_id, l.menu_item_id)}
                      </li>
                    ))}
                  </ul>
                ))}
            </li>
          );
        })}
      </ul>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {state.status === 'closed' ? (
        <p className="cx-note">{t('The host has gone to pay.')}</p>
      ) : (
        <>
          <p className="muted">{t('Your dishes are shared as you add them. Prices are checked again when the host pays.')}</p>
          {state.is_host && (
            <button type="button" onClick={() => void share()}>
              {copied ? t('Link copied') : t('Share the link')}
            </button>
          )}
          {!state.is_host && (
            <button type="button" onClick={() => void share()}>
              {copied ? t('Link copied') : t('Invite someone')}
            </button>
          )}
        </>
      )}
      {state.is_host && state.status === 'open' && (
        <button className="primary" disabled={busy || (others.length === 0 && linesOf(carts).length === 0)} onClick={() => void payForAll()}>
          {t('Add everyone’s dishes and pay')}
        </button>
      )}
      {!state.is_host && (
        <button className="quiet" onClick={forget}>
          {t('Leave the group')}
        </button>
      )}
    </section>
  );
}

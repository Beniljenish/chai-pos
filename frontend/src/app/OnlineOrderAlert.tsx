/**
 * Rings when a customer's online order arrives, on whatever screen the till is showing (README,
 * "9.15"). The banner stays, and the chime repeats gently, until someone taps it. Browsers only
 * allow sound after a tap, so each tablet has one "Sound" switch (remembered on the tablet).
 */
import { useEffect, useRef, useState } from 'react';
import { announce } from '../lib/announce';
import { chime, unlockSound } from '../lib/chime';
import { db } from '../lib/db';
import { liveOrders, type LiveOrder } from '../lib/orders';
import { spotNewOnlineOrders } from '../lib/onlineAlert';
import { onlineToken } from '../lib/table';
import { useSession } from './session';
import { t, useLang } from '../lib/i18n';

const SOUND_KEY = 'taptallow-till-sound';
const REPEAT_MS = 20_000;
const POLL_MS = 10_000;

function soundWanted(): boolean {
  try {
    return localStorage.getItem(SOUND_KEY) === 'on';
  } catch {
    return false;
  }
}

export function OnlineOrderAlert({ onOpen }: { onOpen(): void }) {
  useLang();
  const { sync, worker } = useSession();
  const [sound, setSound] = useState(soundWanted);
  const [fresh, setFresh] = useState<LiveOrder[]>([]);
  const known = useRef<ReadonlySet<string> | null>(null);

  // Keep the tablet's copy of the orders up to date even when Tables is not the screen being shown.
  useEffect(() => {
    const t = setInterval(() => {
      if (document.visibilityState === 'visible') void worker?.kick();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [worker]);

  useEffect(() => {
    // A tablet that has just been set up has an empty copy until its first sync: looking before that
    // would make the whole queue look new.
    if (!sync?.lastSyncedAt) return;
    let live = true;
    void liveOrders(db).then((orders) => {
      if (!live) return;
      const r = spotNewOnlineOrders(known.current, orders);
      known.current = r.known;
      if (r.fresh.length > 0) {
        setFresh((f) => [...f, ...r.fresh]);
        if (sound) chime();
        const token = onlineToken(r.fresh[0].state);
        if (token) announce('order', { token });
      }
    });
    return () => void (live = false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sync?.lastSyncedAt, sync?.pending]);

  // Until someone taps the banner, ring again now and then.
  useEffect(() => {
    if (fresh.length === 0 || !sound) return;
    const t = setInterval(chime, REPEAT_MS);
    return () => clearInterval(t);
  }, [fresh.length, sound]);

  function toggle() {
    const next = !sound;
    if (next) {
      unlockSound(); // this tap is what lets the page make sound
      chime();
    }
    setSound(next);
    try {
      localStorage.setItem(SOUND_KEY, next ? 'on' : 'off');
    } catch {
      /* the switch just resets next time */
    }
  }

  return (
    <>
      <button
        className={`sound-switch ${sound ? 'on' : ''}`}
        role="switch"
        aria-checked={sound}
        onClick={toggle}
        title={t("Ring when a customer's online order arrives")}
      >
        <span aria-hidden="true">{sound ? '🔔' : '🔕'}</span> {t("Sound")} {sound ? 'on' : 'off'}
      </button>
      {fresh.length > 0 && (
        <button
          className="online-alert"
          role="alert"
          onClick={() => {
            setFresh([]);
            onOpen();
          }}
        >
          <span aria-hidden="true">🔔</span>
          <span>
            <strong>
              {t("New online order")}{fresh.length > 1 ? 's' : ''}: {fresh.map((o) => onlineToken(o.state)).join(', ')}
            </strong>
            <small>
              {fresh[fresh.length - 1].state.customer_name.replace(/^[A-Z]{1,2}-\d+ /, '')} {t("· tap to open")}
            </small>
          </span>
        </button>
      )}
    </>
  );
}

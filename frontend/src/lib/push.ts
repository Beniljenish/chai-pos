/** Phone notifications for "your order is ready" (Web Push). The server holds a key pair; the phone
 * subscribes with the public half and gives us an address to send to. All of it is optional: with
 * the server's keys unset, or the browser or the customer saying no, the page still follows the
 * order by itself and chimes if it is open. */
import { publicApi } from './publicApi';

export type PushState = 'unsupported' | 'off' | 'ask' | 'on' | 'denied';

export const pushSupported = (): boolean =>
  typeof navigator !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

function keyBytes(base64Url: string): Uint8Array<ArrayBuffer> {
  const pad = '='.repeat((4 - (base64Url.length % 4)) % 4);
  const raw = atob((base64Url + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

async function subscribeAndTell(token: string, publicKey: string): Promise<boolean> {
  // No service worker (a development server does not register one): give up instead of waiting forever.
  const reg = await Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), 4000)),
  ]);
  if (reg === null) return false;
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }));
  const json = sub.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys.auth) return false;
  await publicApi.pushSubscribe(token, { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } });
  return true;
}

/** Where things stand, quietly. If the customer already said yes, make sure this phone is
 * subscribed under the account that is logged in. */
export async function pushState(token: string): Promise<PushState> {
  if (!pushSupported()) return 'unsupported';
  try {
    const { public_key } = await publicApi.pushKey(token);
    if (!public_key) return 'off';
    if (Notification.permission === 'denied') return 'denied';
    if (Notification.permission === 'granted') {
      await subscribeAndTell(token, public_key);
      return 'on';
    }
    return 'ask';
  } catch {
    return 'off';
  }
}

/** The "Allow notifications" button. Must run from a tap: the browser shows its own question. */
export async function enablePush(token: string): Promise<PushState> {
  if (!pushSupported()) return 'unsupported';
  try {
    const { public_key } = await publicApi.pushKey(token);
    if (!public_key) return 'off';
    const answer = await Notification.requestPermission();
    if (answer !== 'granted') return answer === 'denied' ? 'denied' : 'ask';
    return (await subscribeAndTell(token, public_key)) ? 'on' : 'off';
  } catch {
    return 'off';
  }
}

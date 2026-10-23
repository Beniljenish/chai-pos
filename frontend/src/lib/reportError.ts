/**
 * Errors in someone's app reach the platform admin's error log (README, "9.28"): uncaught
 * errors, failed promises and screens that crash. At most a few per page load, the same one
 * once, and only the path (never the query string, which can carry a token). Reporting must
 * never break the page, so every failure here is swallowed.
 */
const MAX_PER_LOAD = 5;
const seen = new Set<string>();

export function reportError(error: unknown, where = ''): void {
  try {
    const e = error instanceof Error ? error : new Error(String(error));
    const message = `${e.name}: ${e.message}`.slice(0, 2000);
    if (seen.has(message) || seen.size >= MAX_PER_LOAD) return;
    seen.add(message);
    void fetch(`${__API_URL__}/public/app-errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        place: `${where ? where + ' @ ' : ''}${globalThis.location?.pathname ?? ''}`.slice(0, 500),
        detail: (e.stack ?? '').slice(0, 8000),
      }),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* never let reporting break the page */
  }
}

export function installErrorReporting(): void {
  window.addEventListener('error', (ev) => reportError(ev.error ?? ev.message, 'window'));
  window.addEventListener('unhandledrejection', (ev) => reportError(ev.reason, 'promise'));
}

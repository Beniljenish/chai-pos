/** Pickup time slots and the table QR link (README, "9.17"). Pure helpers. */

export interface Slot {
  at: string; // ISO time of the slot's start
  full: boolean;
}

/** "2026-10-22T07:15:00Z" -> "12:45 pm" on an Indian clock, whatever the phone's own zone. */
export function slotLabel(iso: string): string {
  const t = new Date(iso).toLocaleTimeString('en-IN', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'Asia/Kolkata',
  });
  return t.replace(/\s?([ap])m/i, (_m, x: string) => ` ${x.toLowerCase()}m`);
}

/** A table's QR opens /order/<court>?outlet=<id>&table=<name>: which outlet's menu, which table. */
export function tableFromSearch(search: string): { outlet: string | null; table: string } {
  const p = new URLSearchParams(search);
  const table = (p.get('table') ?? '').replace(/[\x00-\x1f]/g, ' ').trim().slice(0, 20);
  const outlet = /^[0-9a-f-]{36}$/i.test(p.get('outlet') ?? '') ? p.get('outlet') : null;
  return { outlet, table };
}

/** The link printed on a table's QR. */
export function tableLink(origin: string, slug: string, outletId: string, table: string): string {
  const q = new URLSearchParams({ outlet: outletId, table });
  return `${origin}/order/${encodeURIComponent(slug)}?${q.toString()}`;
}

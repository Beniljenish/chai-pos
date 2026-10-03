/** Dining floor helpers (tested in floor.test.ts). */

/** Names that continue the area's series: T1..T4 exist -> T5, T6, ... */
export function nextNames(existing: string[], count: number, prefix: string): string[] {
  const taken = new Set(existing.map((n) => n.toUpperCase()));
  const out: string[] = [];
  for (let i = 1; out.length < count && i < 1000; i++) {
    const name = `${prefix}${i}`;
    if (!taken.has(name.toUpperCase())) out.push(name);
  }
  return out;
}

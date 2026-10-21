/** Menu search on the till: pure helpers, tested in search.test.ts. */

const norm = (s: string) => s.toLocaleLowerCase('en-IN').trim();

/** Items whose name or category contains every word typed, in any order. An
 * empty search keeps everything. */
export function searchItems<T extends { name: string; category: string }>(items: T[], query: string): T[] {
  const words = norm(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return items;
  return items.filter((i) => {
    const hay = `${norm(i.name)} ${norm(i.category)}`;
    return words.every((w) => hay.includes(w));
  });
}

export interface NamePart {
  text: string;
  hit: boolean;
}

/** A name split into plain and matching runs, so the match can be highlighted
 * ("Badam milk" for "ba" -> "Ba" hit, "dam milk" plain). */
export function highlightParts(name: string, query: string): NamePart[] {
  const words = norm(query).split(/\s+/).filter(Boolean);
  const lower = name.toLocaleLowerCase('en-IN');
  const mark = new Array<boolean>(name.length).fill(false);
  // Lower-casing can change a string's length (rare scripts); then skip highlighting.
  if (lower.length === name.length) {
    for (const w of words) {
      for (let at = lower.indexOf(w); at !== -1; at = lower.indexOf(w, at + 1)) {
        for (let k = at; k < at + w.length; k++) mark[k] = true;
      }
    }
  }
  const parts: NamePart[] = [];
  for (let k = 0; k < name.length; k++) {
    const last = parts[parts.length - 1];
    if (last && last.hit === mark[k]) last.text += name[k];
    else parts.push({ text: name[k], hit: mark[k] });
  }
  return parts;
}

/**
 * The stylesheet is one long file edited by hand and by merges. A lost "}"
 * silently nests every later rule inside the block above it, so whole screens
 * lose their styles while every behaviour test still passes (this happened once,
 * in a merge). This catches it.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, it } from 'vitest';

const css = readFileSync(resolve(__dirname, 'styles.css'), 'utf8')
  .replace(/\/\*[\s\S]*?\*\//g, '') // comments
  .replace(/"[^"]*"|'[^']*'/g, '""'); // strings (may contain braces)

it('every block is closed', () => {
  let depth = 0;
  let line = 1;
  for (const ch of css) {
    if (ch === '\n') line++;
    if (ch === '{') depth++;
    if (ch === '}') depth--;
    expect(depth, `unbalanced "}" near line ${line}`).toBeGreaterThanOrEqual(0);
  }
  expect(depth, 'a "{" is never closed').toBe(0);
});

it('rules are only nested inside @media or @supports', () => {
  // A selector block opening while another selector block is open means a "}" went missing.
  const stack: string[] = [];
  let head = '';
  for (const ch of css) {
    if (ch === '{') {
      const sel = head.trim();
      const parent = stack[stack.length - 1];
      if (parent !== undefined && !parent.startsWith('@')) {
        throw new Error(`"${sel}" is inside "${parent}": a "}" is missing before it`);
      }
      stack.push(sel);
      head = '';
    } else if (ch === '}') {
      stack.pop();
      head = '';
    } else if (ch === ';') {
      head = '';
    } else {
      head += ch;
    }
  }
  expect(stack).toEqual([]);
});

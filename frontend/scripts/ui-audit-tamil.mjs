// Same as ui-audit.mjs with the app switched to Tamil: longer words are where layouts break.
import { chromium } from '@playwright/test';
const out = process.argv[2];
const SECTIONS = ['Alerts','Sales','Reports','Khata','Watch','Ask','Helpers','Outlets','Special days','Stock','Buy','Margin','Prices paid','Purchases','Day end','Recipes','Shop & GST','Staff','Attendance','Changes','Floor','Food court','Offers','Tablets','Messages'];
const check = () => {
  const vw = window.innerWidth, issues = [];
  if (document.documentElement.scrollWidth > vw + 1) issues.push(`PAGE scrolls sideways (${document.documentElement.scrollWidth}>${vw})`);
  const inScroller = (el) => { for (let e = el.parentElement; e; e = e.parentElement) { const o = getComputedStyle(e).overflowX; if ((o === 'auto' || o === 'scroll') && e.scrollWidth > e.clientWidth) return true; } return false; };
  for (const el of document.querySelectorAll('button, a, input, select, textarea, [role=switch]')) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === 'hidden' || cs.display === 'none') continue;
    const label = (el.getAttribute('aria-label') || el.innerText || el.placeholder || el.className || el.tagName).toString().trim().slice(0, 30).replace(/\n/g, ' ');
    if (r.right > vw + 1 && !inScroller(el)) issues.push(`OFFSCREEN "${label}" right=${Math.round(r.right)}`);
    if ((r.height < 36 || r.width < 36) && el.type !== 'checkbox' && el.type !== 'radio' && !(el.tagName === 'A' && cs.display === 'inline')) issues.push(`SMALL ${Math.round(r.width)}x${Math.round(r.height)} "${label}"`);
  }
  for (const el of document.querySelectorAll('h1,h2,h3,strong,p,span,li,label')) {
    const cs = getComputedStyle(el);
    if (el.children.length === 0 && el.scrollWidth > el.clientWidth + 2 && cs.overflow !== 'visible' && cs.textOverflow !== 'ellipsis' && el.clientWidth > 0) issues.push(`CLIPPED "${el.innerText.slice(0, 30)}"`);
  }
  return [...new Set(issues)];
};
const b = await chromium.launch({ executablePath: process.env.CHROME_PATH });
const report = {};
for (const [name, vp] of [['phone', { width: 390, height: 844 }], ['tablet', { width: 1024, height: 768 }]]) {
  const ctx = await b.newContext({ viewport: vp });
  const p = await ctx.newPage();
  const snap = async (label) => { await p.waitForTimeout(700); const file = `ta-${name}-${label.replace(/[^a-z0-9]+/gi, '-')}`; await p.screenshot({ path: `${out}/${file}.png` }); report[`${name} ${label}`] = await p.evaluate(check); };
  await p.goto('http://localhost:4173/'); await p.waitForTimeout(2200);
  await snap('login');
  await p.getByLabel('Mobile number').fill('9000000001');
  const pw = p.getByLabel('Password'); if (await pw.count()) await pw.fill('e2e-password-123');
  await p.getByRole('button', { name: 'Log in' }).click(); await p.waitForTimeout(1500);
  const setup = p.getByRole('button', { name: 'Set up as a new tablet' });
  if (await setup.count()) { await snap('setup'); await p.getByLabel('Tablet name').fill('Front counter'); await setup.click(); await p.waitForTimeout(2500); }
  await p.evaluate(() => localStorage.setItem('taptallow.lang', 'ta')); await p.reload(); await p.waitForTimeout(2500);
  await snap('bill');
  await p.locator('.tile').first().click(); await p.waitForTimeout(300);
  const handle = p.locator('.till-handle'); if (await handle.isVisible().catch(() => false)) { await handle.click(); await snap('bill-sheet'); await p.keyboard.press('Escape'); await p.waitForTimeout(300); }
  const tabs = p.locator('.tabs button');
  await tabs.nth(1).click(); await snap('tables');
  await tabs.nth(2).click(); await snap('today');
  await tabs.nth(3).click(); await snap('manage-home');
  const n = await p.locator('.subnav-items button').count();
  for (let i = 0; i < n; i++) {
    const back = p.locator('.manage-back');
    if (await back.isVisible().catch(() => false)) await back.click();
    const btn = p.locator('.subnav-items button').nth(i);
    const label = (await btn.getAttribute('aria-label')) || String(i);
    await btn.click(); await snap(`manage-${i}-${label}`);
  }
  await ctx.close();
}
await b.close();
const bad = Object.entries(report).filter(([, v]) => v.length);
console.log(`${Object.keys(report).length} screens, ${bad.length} with findings`);
for (const [k, v] of bad) console.log(`\n## ${k}\n- ` + v.slice(0, 12).join('\n- '));

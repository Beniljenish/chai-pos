/**
 * Accessibility (README, "9.28"): axe-core checks the main screens for problems that stop
 * someone using the app with a screen reader, a keyboard or weak eyesight. Serious and critical
 * findings fail the test; minor ones are listed in the output.
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { expect, test, type Page } from '@playwright/test';
import { openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
// The app's Content-Security-Policy rightly refuses injected scripts; the scan needs one.
test.use({ bypassCSP: true });

const AXE = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8');

type Finding = { id: string; impact: string; help: string; nodes: number; where: string[] };

async function scan(page: Page, where: string): Promise<Finding[]> {
  await page.addScriptTag({ content: AXE });
  const found: Finding[] = await page.evaluate(async () => {
    // @ts-expect-error axe is the script just added
    const r = await window.axe.run(document, { resultTypes: ['violations'] });
    return r.violations.map(
      (v: { id: string; impact: string; help: string; nodes: { target: string[]; any: { message: string }[] }[] }) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        nodes: v.nodes.length,
        where: v.nodes.slice(0, 6).map((n) => `${n.target.join(' ')} :: ${n.any[0]?.message ?? ''}`),
      }),
    );
  });
  for (const f of found) {
    console.log(`[a11y] ${where}: ${f.impact} ${f.id} (${f.nodes}) ${f.help}`);
    for (const w of f.where) console.log(`[a11y]    ${w}`);
  }
  return found.filter((f) => f.impact === 'serious' || f.impact === 'critical');
}

test('the main screens have no serious accessibility problems', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible();
  const bad: Record<string, Finding[]> = {};
  bad.login = await scan(page, 'login');

  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E a11y phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await expect(page.locator('.tile').first()).toBeVisible();
  bad.till = await scan(page, 'till');

  const tabs = page.locator('.tabs');
  await tabs.getByRole('button', { name: 'Today' }).click();
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible();
  bad.today = await scan(page, 'today');

  // Tables appears once the shop has tables (another spec makes them); scan it when it is there.
  const tablesTab = tabs.getByRole('button', { name: 'Tables' });
  if (await tablesTab.isVisible()) {
    await tablesTab.click();
    await expect(page.getByRole('heading', { name: 'Tables' })).toBeVisible();
    bad.tables = await scan(page, 'tables');
  }

  await tabs.getByRole('button', { name: 'Manage' }).click();
  bad.manage = await scan(page, 'manage');
  for (const section of ['Sales', 'Stock', 'Day end']) {
    await openSection(page, section);
    await expect(page.getByRole('heading', { name: section }).first()).toBeVisible();
    bad[section] = await scan(page, section);
  }

  await page.goto('/order');
  await expect(page.getByLabel('Mobile number')).toBeVisible();
  bad.customer = await scan(page, 'customer login');

  const serious = Object.entries(bad).filter(([, v]) => v.length);
  expect(serious, JSON.stringify(serious, null, 1)).toEqual([]);
});

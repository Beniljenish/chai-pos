/**
 * The lost-bill alarm, end to end: a bill is printed but cannot reach the
 * server; the tablet reports holding it; then the browser storage is wiped.
 * The tablet must resume numbering AFTER the lost number (never reprint it), and
 * the owner's Tablets screen must name the missing invoice.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const TABLET = 'E2E safety phone';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });
const sub = (page: Page, name: string) => page.locator('.subnav').getByRole('button', { name, exact: true });

async function logIn(page: Page) {
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
}

/** Sell one tea; returns the invoice number printed. */
async function sellTea(page: Page): Promise<string> {
  await tab(page, 'New bill').click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Save and print' }).click();
  const receipt = page.getByRole('dialog');
  await expect(receipt).toBeVisible();
  const label = (await receipt.getAttribute('aria-label')) ?? '';
  await receipt.getByRole('button', { name: 'New bill', exact: true }).click();
  return label.replace('Bill ', '');
}

test('a printed bill lost in a browser wipe is named, and its number is never reused', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await logIn(page);
  await page.getByLabel('Tablet name').fill(TABLET);
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  const first = await sellTea(page);
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  // ---- The next bill cannot reach the server (bills only; reports still get through) ----
  await page.route('**/sync/bills', (route) => route.abort());
  const reported = page.waitForRequest(
    (r) => r.url().includes('/report') && (r.postData() ?? '').includes('"pending_bills":1'),
  );
  const lost = await sellTea(page);
  await reported; // the tablet told the server it printed this one and still holds it

  // ---- The browser storage is wiped (the bill was never sent) ----
  await page.evaluate(
    () =>
      new Promise<void>((done) => {
        const req = indexedDB.deleteDatabase('chai-pos');
        req.onsuccess = req.onerror = req.onblocked = () => done();
      }),
  );
  await page.unroute('**/sync/bills');
  await page.reload();
  await logIn(page);
  await page.getByText('This tablet was set up before').click();
  await page.getByRole('button', { name: new RegExp(TABLET) }).click();

  // ---- Numbering resumes AFTER the lost bill: its number is never printed twice ----
  const next = await sellTea(page);
  const seq = (n: string) => Number(n.split('/')[2]);
  expect(seq(lost)).toBe(seq(first) + 1);
  expect(seq(next)).toBe(seq(lost) + 1);
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  // ---- The owner is told exactly which bill is missing ----
  await tab(page, 'Manage').click();
  await sub(page, 'Tablets').click();
  const card = page.locator('.tablet-list > li', { hasText: TABLET });
  await expect(card).toContainText('1 printed bill never reached the server');
  await expect(card).toContainText(lost);
  await expect(card).not.toContainText(next);
  await card.scrollIntoViewIfNeeded();
  await shot(page, '60-tablets-lost-bill');
});

/**
 * Day end in a real browser: wastage, the blind count with a recount, the
 * owner's variance report and approval; and the cashier's restricted view.
 * Today's count is left unapproved so later specs' sales are unaffected; the
 * approval is exercised on yesterday (a quiet day: everything exact).
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const CASHIER = process.env.E2E_CASHIER ?? '9000000002';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

async function login(page: Page, phone: string, tablet: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(phone);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  if (phone === OWNER) {
    await page.getByLabel('Tablet name').fill(tablet);
    await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  }
}

test('owner: wastage, blind count with recount, variance, approval', async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, OWNER, 'E2E dayend phone');

  // Two teas sold today, so decoction has usage the count can disagree with.
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Save and print' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'New bill', exact: true }).click();
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  await tab(page, 'Manage').click();
  await page.locator('.subnav').getByRole('button', { name: 'Day end' }).click();
  await expect(page.getByRole('heading', { name: 'Day end' })).toBeVisible();

  // ---- Wastage: one tea spilled ----
  const w = page.locator('.wastage');
  await w.getByLabel('Which drink').selectOption({ label: 'Masala tea' });
  await w.getByRole('radio', { name: 'Spilled / dropped' }).click();
  await w.getByRole('button', { name: 'Record wastage' }).click();
  await expect(w.getByRole('status')).toContainText('Recorded: 1 × Masala tea, spilled / dropped');

  // ---- Blind count: everything zero. Decoction and others that moved get a recount. ----
  const count = page.locator('.count');
  await expect(count).not.toContainText('expected');
  const zeros = count.getByRole('button', { name: 'It is zero' });
  const n = await zeros.count();
  for (let i = 0; i < n; i++) await zeros.nth(i).click();
  await shot(page, '40-count');
  await count.getByRole('button', { name: 'Send count' }).click();
  await expect(count.getByRole('heading', { name: 'Please count these again' })).toBeVisible();
  await expect(count.locator('.count-list li', { hasText: 'Tea decoction' })).toBeVisible();
  await shot(page, '41-recount');
  const again = count.getByRole('button', { name: 'It is zero' });
  const m = await again.count();
  for (let i = 0; i < m; i++) await again.nth(i).click();
  await count.getByRole('button', { name: 'Send recount' }).click();
  await expect(count.getByRole('status')).toContainText('Count sent to the owner');
  await expect(count.getByRole('button', { name: 'Count again' })).toBeVisible();

  // ---- The owner's variance report ----
  const report = page.locator('.report');
  const decoction = report.locator('.variance-list li', { hasText: 'Tea decoction' });
  await expect(decoction).toContainText('Recounted');
  await decoction.locator('summary').click();
  await expect(decoction).toContainText('− Sold (by recipe)');
  await expect(decoction).toContainText('− Wasted');
  await shot(page, '42-variance');
  await expect(report.getByRole('button', { name: 'Approve and close the day' })).toBeVisible();

  // ---- Approve yesterday (quiet: all exact) ----
  await page.getByRole('radio', { name: /^Yesterday/ }).click();
  // Wait for yesterday's sheet to load (today's sent count shows no list).
  await expect(count.getByRole('button', { name: 'It is zero' }).first()).toBeVisible();
  const zerosY = count.getByRole('button', { name: 'It is zero' });
  const k = await zerosY.count();
  for (let i = 0; i < k; i++) await zerosY.nth(i).click();
  await count.getByRole('button', { name: 'Send count' }).click();
  await expect(count.getByRole('status')).toContainText('Count sent to the owner');
  await report.getByRole('button', { name: 'Approve and close the day' }).click();
  await report.getByRole('button', { name: 'Yes, close the day' }).click();
  await expect(report).toContainText('Closed by');
  await expect(count).toContainText('This day is closed');
  await shot(page, '43-closed');
});

test('cashier: batches, wastage and a blind count; no rupees, no report', async ({ page }) => {
  // The owner sets the tablet up once; then the cashier works on it.
  await login(page, OWNER, 'E2E counter for cashier');
  await page.getByRole('button', { name: 'Log out' }).click();
  await page.getByLabel('Mobile number').fill(CASHIER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.locator('.where')).toContainText('Cashier');

  await tab(page, 'Stock').click();
  await expect(page.getByRole('heading', { name: 'Stock tasks' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Made a batch?' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Something wasted?' })).toBeVisible();
  await expect(page.locator('.count')).toBeVisible();
  // Blind and rupee-free: no variance report, no stock levels, no owner-only reasons.
  await expect(page.getByRole('heading', { name: 'Variance' })).toHaveCount(0);
  await expect(page.locator('main')).not.toContainText('₹');
  await page.locator('.wastage').getByLabel('Which drink').selectOption({ label: 'Masala tea' });
  await expect(page.getByRole('radio', { name: 'Free (on the house)' })).toHaveCount(0);
  await expect(page.getByRole('radio', { name: 'Theft / unexplained' })).toHaveCount(0);
  await shot(page, '44-cashier-stock');
});

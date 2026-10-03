/**
 * The owner's sales report and voiding a bill, on a phone: a bill billed twice
 * is voided with a reason, drops out of the day's total, shows in the Voided
 * list and on the tablet's Today screen, and its stock comes back.
 * Other specs sell on the same day, so totals are checked as differences.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });
const sub = (page: Page, name: string) => page.locator('.subnav').getByRole('button', { name, exact: true });
const rupees = (s: string | null) => Number((s ?? '').replace(/[^0-9.]/g, ''));

async function sellTeas(page: Page, n: number): Promise<string> {
  await tab(page, 'New bill').click();
  const tile = page.locator('.tile', { hasText: 'Masala tea' });
  for (let i = 0; i < n; i++) await tile.click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Save and print' }).click();
  const label = await sheet(page).getAttribute('aria-label'); // "Bill C3/26-27/000002"
  await sheet(page).getByRole('button', { name: 'New bill', exact: true }).click();
  return (label ?? '').replace('Bill ', '');
}

test('owner voids a bill billed twice; the sales report leaves it out', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E sales phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await sellTeas(page, 2); // ₹40, kept
  const twice = await sellTeas(page, 2); // the same order again: to be voided
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  // ---- Manage opens on Sales ----
  await tab(page, 'Manage').click();
  await expect(sub(page, 'Sales')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: 'Sales', exact: true })).toBeVisible();
  await expect(page.locator('.day-now')).toHaveText('Today');
  const before = rupees(await page.locator('.sales-total .big').textContent());
  await expect(page.locator('.sales-table', { hasText: 'Masala tea' })).toBeVisible();
  await shot(page, '30-sales');

  // ---- Void the duplicate ----
  await page.locator('.bill-list li', { hasText: twice }).click();
  await expect(sheet(page)).toContainText('2 × Masala tea');
  await sheet(page).getByRole('button', { name: 'Void this bill' }).click();
  await sheet(page).getByRole('button', { name: 'Void ₹40' }).click();
  await expect(sheet(page).getByRole('alert')).toContainText('Choose why');
  await sheet(page).getByRole('radio', { name: 'Billed twice' }).check();
  await sheet(page).getByLabel('Note (optional)').fill('same customer, tapped save twice');
  await shot(page, '31-void-form');
  await sheet(page).getByRole('button', { name: 'Void ₹40' }).click();
  await expect(sheet(page).getByRole('status')).toContainText('Voided');
  await expect(sheet(page).getByRole('status')).toContainText('Billed twice (same customer, tapped save twice)');
  await expect(sheet(page).getByRole('status')).toContainText('Stock was put back.');
  await expect(sheet(page).getByRole('button', { name: 'Void this bill' })).toHaveCount(0);
  await sheet(page).getByRole('button', { name: 'Close' }).click();

  // ---- Report: ₹40 less, listed under Voided, bill struck through ----
  await expect.poll(async () => rupees(await page.locator('.sales-total .big').textContent())).toBe(before - 40);
  await expect(page.locator('.sales-total')).toContainText('1 voided (₹40, not included)');
  await expect(page.locator('.void-list li', { hasText: twice })).toContainText('Billed twice');
  await expect(page.locator('.bill-list li', { hasText: twice })).toContainText('Voided');
  await shot(page, '32-sales-after-void');

  // ---- Stock came back: 2 teas of decoction (100 ml each, or 120 after the recipes spec's v2) ----
  await sub(page, 'Stock').click();
  await page.locator('.stock-list li', { hasText: 'Tea decoction' }).click();
  const top = sheet(page).locator('.ledger li').first();
  await expect(top).toContainText('Bill cancelled');
  await expect(top).toContainText(/\+(200|240) ml/);
  await sheet(page).getByRole('button', { name: 'Close' }).click();

  // ---- The tablet's Today screen shows it too ----
  await tab(page, 'Today').click();
  await expect(page.locator('.bill-list li', { hasText: twice })).toContainText('Voided');
  await expect(page.locator('.bills-head')).toContainText('voided');
  await shot(page, '33-today-voided');
});

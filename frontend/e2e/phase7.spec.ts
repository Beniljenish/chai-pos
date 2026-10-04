/**
 * Phase 7 on the owner's phone: a supplier, a purchase order (tea powder: no
 * other spec counts it) received into
 * stock (less than ordered, at a different price), a reorder level that makes
 * "Fill from reorder levels" propose the item, and the Reports screen with CSV
 * downloads. Other specs sell on the same day, so nothing here checks totals.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

test('buying stock and reading reports', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E purchases phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // ---- A supplier and an order for 10 L of milk ----
  await tab(page, 'Manage').click();
  await openSection(page, 'Purchases');
  await page.getByRole('button', { name: '+ Supplier' }).click();
  await sheet(page).getByLabel('Name').fill('Aavin agent');
  await sheet(page).getByLabel(/Note/).fill('Comes at 6 am');
  await sheet(page).getByRole('button', { name: 'Add supplier' }).click();
  await page.getByRole('button', { name: '+ Order' }).click();
  const order = page.getByRole('dialog', { name: 'New order' });
  await order.getByLabel('Item 1').selectOption({ label: 'Tea powder' });
  await order.getByLabel('Qty (kg)').fill('2');
  await order.getByLabel('Expected ₹').fill('900');
  await shot(page, '110-new-order');
  await order.getByRole('button', { name: 'Save order (₹900)' }).click();
  const po = page.locator('.po-list li', { hasText: 'Aavin agent' }).first();
  await expect(po).toContainText('Ordered');

  // ---- 1.5 kg came, at 700 ----
  await po.click();
  const recv = page.getByRole('dialog', { name: 'Aavin agent: Ordered' });
  await recv.getByLabel('Came (kg)').fill('1.5');
  await recv.getByLabel('Paid ₹').fill('700');
  await recv.getByRole('button', { name: 'Receive into stock' }).click();
  await expect(po).toContainText('Received');
  await expect(po).toContainText('Tea powder 1.5 kg');

  // ---- Stock shows it; a reorder level of 100 kg marks it and proposes it ----
  await openSection(page, 'Stock');
  await page.locator('.stock-list li', { hasText: 'Tea powder' }).click();
  await expect(sheet(page).locator('.ledger li').first()).toContainText('+1.5 kg');
  await sheet(page).getByLabel('Reorder below (kg)').fill('100');
  await sheet(page).getByRole('button', { name: 'Save', exact: true }).click();
  await sheet(page).getByRole('button', { name: 'Close' }).click();
  await expect(page.locator('.stock-list li', { hasText: 'Tea powder' })).toContainText('Reorder');
  await openSection(page, 'Purchases');
  await page.getByRole('button', { name: '+ Order' }).click();
  await page.getByRole('button', { name: 'Fill from reorder levels' }).click();
  const proposed = page.getByRole('dialog', { name: 'New order' }).getByLabel(/^Item \d/);
  await expect(proposed.locator('option:checked')).toContainText(['Tea powder']);
  await page.getByRole('dialog', { name: 'New order' }).getByRole('button', { name: 'Cancel' }).click();

  // ---- Reports, with CSV downloads ----
  await openSection(page, 'Reports');
  await expect(page.getByRole('heading', { name: 'Sales over time' })).toBeVisible();
  await expect(page.locator('.reports .sales-total')).toBeVisible();
  const items = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download items (CSV)' }).click();
  expect((await items).suggestedFilename()).toMatch(/^sales-by-item-\d{4}-\d{2}-\d{2}-to-\d{4}-\d{2}-\d{2}\.csv$/);
  await expect(page.getByRole('heading', { name: 'GST for a month' })).toBeVisible();
  const hsn = page.waitForEvent('download');
  await page.getByRole('button', { name: 'HSN (CSV)' }).click();
  expect((await hsn).suggestedFilename()).toMatch(/^gstr1-hsn-\d{4}-\d{2}\.csv$/);
  await expect(page.locator('section', { hasText: 'Stock value' }).last()).toContainText('Tea powder');
  await shot(page, '111-reports');
});

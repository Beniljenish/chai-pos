/** The owner sets up the dining floor on a phone: areas, bulk-added tables, edits. */
import { expect, test, type Page } from '@playwright/test';
import { openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

test('owner sets up areas and tables', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E floor phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await tab(page, 'Manage').click();
  await openSection(page, 'Floor');
  await expect(page.locator('.empty-card')).toContainText('No tables yet');

  // ---- An area, then six tables in one go ----
  await page.getByRole('button', { name: '+ Area' }).click();
  await sheet(page).getByRole('button', { name: 'Hall' }).click();
  await sheet(page).getByRole('button', { name: 'Add area' }).click();
  const hall = page.locator('.area-card', { hasText: 'Hall' });
  await hall.getByRole('button', { name: 'Add tables to Hall' }).click();
  await sheet(page).getByLabel('How many').fill('6');
  await expect(sheet(page)).toContainText('Will add: T1, T2, T3, T4, T5, T6');
  await shot(page, '80-add-tables');
  await sheet(page).getByRole('button', { name: 'Add 6 tables' }).click();
  await expect(hall.locator('.table-chips li')).toHaveCount(7); // six tables and the add button
  await expect(hall).toContainText('6 tables · 24 seats');

  // ---- A second area continues with its own names ----
  await page.getByRole('button', { name: '+ Area' }).click();
  await sheet(page).getByLabel('Name', { exact: true }).fill('Outdoor');
  await sheet(page).getByRole('button', { name: 'Add area' }).click();
  const outdoor = page.locator('.area-card', { hasText: 'Outdoor' });
  await outdoor.getByRole('button', { name: 'Add tables to Outdoor' }).click();
  await sheet(page).getByLabel('How many').fill('2');
  await sheet(page).getByLabel('Name starts with').fill('P');
  await sheet(page).getByLabel('Seats each').fill('2');
  await sheet(page).getByRole('button', { name: 'Add 2 tables' }).click();
  await expect(outdoor).toContainText('2 tables · 4 seats');

  // ---- Edit a table; switch one off ----
  await hall.getByRole('button', { name: /^T6/ }).click();
  await sheet(page).getByLabel('Seats').fill('8');
  await sheet(page).getByRole('button', { name: 'Save' }).click();
  await expect(hall).toContainText('6 tables · 28 seats');
  await hall.getByRole('button', { name: /^T5/ }).click();
  await sheet(page).getByRole('button', { name: 'Switch off' }).click();
  await expect(hall).toContainText('5 tables · 24 seats');
  await shot(page, '81-floor');
});

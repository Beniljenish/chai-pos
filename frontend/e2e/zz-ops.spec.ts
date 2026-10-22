/**
 * Owner tools and customer erase (README, "9.21"): clock in and out, the owner's hours sheet, the
 * change log, prices paid, special days; and a customer deleting their own account. Starts with zz
 * so it runs after the specs whose data it must not disturb.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection, submitSignup } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const phone = { width: 390, height: 844 };

test('owner: attendance, change log, prices paid and special days', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize(phone);
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E ops phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await expect(page.locator('.tile').first()).toBeVisible();

  // ---- clock in on Today, then see it on the owner's sheet
  await page.locator('.tabs').getByRole('button', { name: 'Today' }).click();
  const card = page.getByRole('region', { name: 'Attendance' });
  await expect(card).toContainText('Not clocked in');
  await card.getByRole('button', { name: 'Clock in' }).click();
  await expect(card).toContainText('Clocked in at');
  await shot(page, 'ops-1-clock');
  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await openSection(page, 'Attendance');
  await expect(page.getByRole('heading', { name: 'Attendance' })).toBeVisible();
  await expect(page.locator('.attendance')).toContainText('still in');
  await page.getByLabel('Hourly rate (₹)').first().fill('60');
  await page.getByRole('button', { name: 'Save rate' }).first().click();
  await expect(page.locator('.attendance')).toContainText('₹60');
  await page.locator('.tabs').getByRole('button', { name: 'Today' }).click();
  await page.getByRole('region', { name: 'Attendance' }).getByRole('button', { name: 'Clock out' }).click();
  await expect(page.getByRole('region', { name: 'Attendance' })).toContainText('Not clocked in');

  // ---- the change log has the rate change
  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await openSection(page, 'Changes');
  await expect(page.getByRole('list', { name: 'Changes' })).toContainText('Hourly rate changed');
  await shot(page, 'ops-2-changes');

  // ---- prices paid (the demo shop has stock-in prices; either list or the empty note is fine)
  await openSection(page, 'Prices paid');
  await expect(page.getByRole('heading', { name: 'Prices paid' })).toBeVisible();

  // ---- a special day, with a fixed-date suggestion offered
  await openSection(page, 'Special days');
  await page.getByLabel('Name', { exact: true }).fill('E2E Festival');
  const d = new Date(Date.now() + 20 * 86400_000).toISOString().slice(0, 10);
  await page.getByLabel('Date', { exact: true }).fill(d);
  await page.getByRole('button', { name: 'Add special day' }).click();
  await expect(page.getByRole('region', { name: 'E2E Festival' })).toContainText('last year');
  await shot(page, 'ops-3-special-days');
});

test('a customer deletes their own account', async ({ browser }) => {
  test.setTimeout(90_000);
  const customer = await (await browser.newContext({ viewport: phone })).newPage();
  await customer.goto('/order');
  await customer.getByLabel('Your name').fill('Erase Me');
  await customer.getByLabel('Mobile number').fill('98400 44444');
  await customer.getByLabel('Choose a password').fill('erase-secret-77');
  await submitSignup(customer);
  await expect(customer.getByRole('heading', { name: 'Where are you eating?' })).toBeVisible();
  await customer.getByRole('button', { name: 'My orders' }).click();
  await customer.getByRole('button', { name: 'Delete my account' }).click();
  await expect(customer.getByText('This cannot be undone.')).toBeVisible();
  await customer.getByLabel('Your password').fill('wrong-password-1');
  await customer.getByRole('button', { name: 'Yes, delete my account' }).click();
  await expect(customer.getByRole('alert')).toContainText('not right');
  await customer.getByLabel('Your password').fill('erase-secret-77');
  await customer.getByRole('button', { name: 'Yes, delete my account' }).click();
  await expect(customer.getByRole('heading', { name: 'Order from your food court' })).toBeVisible();
  await shot(customer, 'ops-4-deleted');
});

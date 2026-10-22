/**
 * The owner's helpers (README, "9.17"): the commission calculator, tomorrow's prep, the switch
 * that hides a dish when its ingredient is gone, and the daily summary message. The backend runs
 * with no message service, so "Send me one now" shows what would be sent. Starts with zz so it
 * runs after the specs whose settings it must not disturb, and leaves every switch off.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });

test('owner: commission calculator, prep, switches and the summary message', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E helpers phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await expect(page.locator('.tile').first()).toBeVisible();

  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await openSection(page, 'Helpers');
  await expect(page.getByRole('heading', { name: 'Helpers' })).toBeVisible();

  // ---- what delivery apps cost: ₹40,000 at 25% is ₹10,000; direct at 2% is ₹800
  await page.getByLabel('Sales through the apps this month (₹)').fill('40000');
  await page.getByLabel('Their commission and charges (%)').fill('25');
  await page.getByLabel(/What a direct order costs you/).fill('2');
  const calc = page.getByRole('region', { name: 'What delivery apps cost you' });
  await expect(calc).toContainText('₹10,000');
  await expect(calc).toContainText('₹800');
  await expect(calc).toContainText('₹9,200');

  // ---- tomorrow's prep is a guide from history; a fresh shop may have nothing yet
  await expect(page.getByRole('region', { name: /Tomorrow’s prep/ })).toContainText('Average of the last 4 same weekdays');

  // ---- the switches: the summary needs a number first
  const hide = page.getByRole('switch', { name: 'Hide a dish when its ingredient runs out' });
  await hide.click();
  await expect(hide).toHaveAttribute('aria-checked', 'true');
  await hide.click();
  await expect(hide).toHaveAttribute('aria-checked', 'false');
  const summary = page.getByRole('switch', { name: 'Daily summary message' });
  await expect(summary).toBeDisabled();
  await page.getByLabel('Your mobile number').fill('98400 77777');
  await page.getByRole('button', { name: 'Save number' }).click();
  await expect(page.getByLabel('Your mobile number')).toHaveValue('9840077777');
  await summary.click();
  await expect(summary).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: 'Send me one now' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'No message service is set up' })).toContainText('Sales');
  await shot(page, 'helpers-1');
  await summary.click();
  await expect(summary).toHaveAttribute('aria-checked', 'false');
});

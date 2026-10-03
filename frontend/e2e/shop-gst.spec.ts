/**
 * GST settings, end to end: a mistyped GSTIN is refused, registering as regular
 * GST previews the tax split, and the next real sale prints a tax invoice with
 * the GSTIN and the CGST/SGST rates.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const GSTIN = '33ABCDE1234F1Z7'; // synthetic, valid check digit, Tamil Nadu
const TYPO = '33ABCDE1243F1Z7'; // two digits swapped
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

test('owner GST: mistyped GSTIN refused, regular GST prints a tax invoice', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E gst phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await tab(page, 'Manage').click();
  await page.locator('.subnav').getByRole('button', { name: 'Shop & GST' }).click();
  await expect(page.getByRole('heading', { name: 'Shop & GST' })).toBeVisible();

  await page.getByRole('radio', { name: /Regular GST/ }).check();
  const save = page.getByRole('button', { name: 'Save shop settings' });
  await expect(save).toBeDisabled(); // regular needs a GSTIN

  await page.getByRole('textbox', { name: /^GSTIN/ }).fill(TYPO);
  await expect(page.locator('#gstin-help')).toContainText('mistyped');
  await expect(save).toBeDisabled();

  await page.getByRole('textbox', { name: /^GSTIN/ }).fill(GSTIN.toLowerCase());
  await expect(page.locator('#gstin-help')).toContainText('Valid · registered in Tamil Nadu');
  // Rs 20 tea, 5% included (rule shared with backend/app/services/gst.py):
  // taxable backed out = 19.05; CGST = SGST = 2.5% of 19.05 = 0.476 -> 0.48;
  // that totals 20.01, so the taxable value absorbs the paisa: 19.04 + 0.48
  // + 0.48 = 20.00 exactly, the menu price.
  const preview = page.locator('.preview');
  await expect(preview).toContainText('Tax invoice');
  await expect(preview).toContainText('CGST @2.5%₹0.48');
  await expect(preview).toContainText('SGST @2.5%₹0.48');
  await expect(preview).toContainText('Taxable value₹19.04');
  await expect(preview).toContainText('Customer pays₹20');
  await shot(page, '30-shop-gst');
  await save.click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();

  // ---- Menu prices: an 18% item is shown as such ----
  await expect(page.locator('#menu-title')).toBeVisible();
  await shot(page, '31-menu-prices');

  // ---- The next sale is a tax invoice with GSTIN and rates ----
  await tab(page, 'New bill').click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Save and print' }).click();
  const receipt = page.locator('.receipt');
  await expect(receipt).toContainText('Tax invoice');
  await expect(receipt).toContainText(`GSTIN ${GSTIN}`);
  await expect(receipt).toContainText('CGST @2.5%');
  await expect(receipt).toContainText('SGST @2.5%');
  await shot(page, '32-tax-invoice');
});

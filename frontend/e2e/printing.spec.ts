/**
 * Printing through RawBT, end to end (no printer here: the app announces each
 * rawbt: link it would open, and the test decodes the ESC/POS bytes in it).
 */
import { expect, test, type Page } from '@playwright/test';
import { saveAndPrint } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

/** The text of the last receipt sent to RawBT: base64 -> bytes -> printable characters. */
async function lastPrinted(page: Page): Promise<string> {
  return page.evaluate(() => {
    const prints = (window as unknown as { __prints: string[] }).__prints;
    const url = prints[prints.length - 1] ?? '';
    const bytes = atob(url.replace('rawbt:base64,', ''));
    // Drop the printer commands (ESC @, ESC a n, ESC E n, ESC d n, GS ! n, GS V m n), keep the text.
    return bytes
      .replace(/\x1b@|\x1b[aEd][\s\S]|\x1d![\s\S]|\x1dV[\s\S][\s\S]/g, '')
      .replace(/[^\x20-\x7e\n]/g, '');
  });
}

test('RawBT printing: test print, auto-print on save, reprint from Today', async ({ page }) => {
  test.setTimeout(90_000);
  await page.addInitScript(() => {
    const w = window as unknown as { __prints: string[] };
    w.__prints = [];
    window.addEventListener('chai-pos:print', (e) => w.__prints.push((e as CustomEvent<string>).detail));
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E printer phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // ---- Choose RawBT on this tablet and send a test print ----
  await tab(page, 'Today').click();
  await page.getByRole('button', { name: 'Printer', exact: true }).click();
  await sheet(page).getByLabel(/RawBT app/).check();
  await expect(sheet(page).getByLabel('58 mm')).toBeChecked();
  await shot(page, '70-printer-settings');
  await sheet(page).getByRole('button', { name: 'Test print' }).click();
  await expect(sheet(page).getByRole('status')).toContainText('Sent to the printer');
  expect(await lastPrinted(page)).toContain('TEST PRINT');
  await sheet(page).getByRole('button', { name: 'Done' }).click();

  // ---- A saved bill prints by itself, laid out for 58 mm ----
  await tab(page, 'New bill').click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await saveAndPrint(page);
  const invoice = ((await sheet(page).getAttribute('aria-label')) ?? '').replace('Bill ', '');
  await expect.poll(async () => (await lastPrinted(page)).includes(invoice)).toBe(true);
  const receipt = await lastPrinted(page);
  // The demo shop is not GST-registered yet at this point (shop-gst.spec runs later): title BILL.
  for (const words of ['BILL', 'Masala tea', 'TOTAL', 'Rs.20', 'Paid by', 'Thank you']) expect(receipt).toContain(words);
  for (const line of receipt.split('\n')) expect(line.length).toBeLessThanOrEqual(32);
  await sheet(page).getByRole('button', { name: 'New bill', exact: true }).click();

  // ---- Reprint from Today is marked as a reprint ----
  await tab(page, 'Today').click();
  await page.locator('.bill-list li', { hasText: invoice }).click();
  await sheet(page).getByRole('button', { name: 'Reprint' }).click();
  await expect.poll(async () => (await lastPrinted(page)).includes('(Reprint)')).toBe(true);
});

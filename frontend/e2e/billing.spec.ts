/**
 * End-to-end in a real browser: log in, set up the tablet, sell, lose the
 * network, keep selling, reload the app with NO network (service worker), get
 * the network back, and watch every bill reach the server once.
 * Screenshots go to e2e-screenshots/ (uploaded by CI) for visual review.
 */
import { expect, request, test, type Page } from '@playwright/test';
import { saveAndPrint } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const API = process.env.E2E_API_URL ?? 'http://localhost:8000/api/v1';
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });

async function serverBillCount(): Promise<number> {
  const ctx = await request.newContext();
  const login = await ctx.post(`${API}/auth/login`, { data: { phone: OWNER, password: PASSWORD } });
  const { access_token } = await login.json();
  const bills = await ctx.get(`${API}/bills`, { headers: { Authorization: `Bearer ${access_token}` } });
  const n = (await bills.json()).length;
  await ctx.dispose();
  return n;
}

async function sell(page: Page, item: string, times = 1) {
  const tile = page.locator('.tile', { hasText: item });
  for (let i = 0; i < times; i++) await tile.click();
}
const category = (page: Page, name: string) =>
  page.locator('.categories').getByRole('button', { name, exact: true });
const newBillOnReceipt = (page: Page) =>
  page.getByRole('dialog').getByRole('button', { name: 'New bill', exact: true });
const tab = (page: Page, name: string) =>
  page.locator('.tabs').getByRole('button', { name, exact: true });

test('offline billing, end to end', async ({ page, context }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 800 }); // a landscape tablet
  const before = await serverBillCount();

  // ---- Log in and set up this tablet ----
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Chai POS' })).toBeVisible();
  await shot(page, '01-login');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();

  await expect(page.getByRole('heading', { name: 'Set up this tablet' })).toBeVisible();
  await shot(page, '02-setup');
  await page.getByLabel('Tablet name').fill('E2E counter');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // ---- A sale online: 2 teas + a Large juice ----
  await expect(page.locator('.tile', { hasText: 'Masala tea' })).toBeVisible();
  await page.evaluate(() => navigator.serviceWorker.ready); // app shell cached for offline
  await shot(page, '03-billing-empty');
  await sell(page, 'Masala tea', 2);
  await category(page, 'Juice').click();
  await sell(page, 'Orange juice');
  await page.locator('.lines li', { hasText: 'Orange juice' }).getByRole('button', { name: /^Large/ }).click();
  // 2 x Rs 20 + (Rs 60 + Rs 10) = Rs 110
  await expect(page.locator('.total strong')).toHaveText('₹110');
  await shot(page, '04-billing-cart');
  await saveAndPrint(page);
  await expect(page.getByRole('dialog')).toContainText('₹110');
  await shot(page, '05-receipt');
  await newBillOnReceipt(page).click();
  await expect(page.getByText('All bills sent')).toBeVisible({ timeout: 15_000 });

  // ---- The internet goes down: keep selling ----
  await context.setOffline(true);
  for (let i = 0; i < 3; i++) {
    await category(page, 'Tea').click();
    await sell(page, 'Masala tea');
    await saveAndPrint(page);
    await newBillOnReceipt(page).click();
  }
  await expect(page.getByText('3 waiting to send')).toBeVisible({ timeout: 15_000 });
  await shot(page, '06-offline-waiting');

  // ---- Reload with NO network: the app must still open, bills intact ----
  await page.reload();
  await expect(page.locator('.tile', { hasText: 'Masala tea' })).toBeVisible();
  await expect(page.getByText('3 waiting to send')).toBeVisible({ timeout: 15_000 });

  // ---- Back online: everything goes, once ----
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByText('All bills sent')).toBeVisible({ timeout: 30_000 });
  await tab(page, 'Today').click();
  await expect(page.locator('.status.synced')).toHaveCount(4);
  await shot(page, '07-today');
  expect(await serverBillCount()).toBe(before + 4);

  // ---- Phone layout ----
  await page.setViewportSize({ width: 390, height: 844 });
  await tab(page, 'New bill').click();
  await sell(page, 'Masala tea');
  await shot(page, '08-phone-bar');
  await page.locator('.till-handle').click();
  await shot(page, '09-phone-till-open');
});

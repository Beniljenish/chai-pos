/**
 * Owner stock, end to end in a real browser against the real API:
 * opening count by pack, stock-in, logging a decoction batch (which must take
 * milk out), and the history behind the number. Screenshots for review.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });

const row = (page: Page, name: string) => page.locator('.stock-list li', { hasText: name });
const sheet = (page: Page) => page.getByRole('dialog');

async function plus(page: Page, pack: string, times: number) {
  for (let i = 0; i < times; i++) await sheet(page).getByRole('button', { name: `One ${pack} more` }).click();
}

test('owner stock: opening count, stock-in, batch, history', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 }); // the phone the owner carries

  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E owner phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  // Manage opens on Sales (what the owner checks most); Stock is one tap away.
  // The first load fails (a network blip): the screen says so and reloads in place.
  await page.route('**/api/v1/stock', (r) => r.abort('internetdisconnected'));
  await page.locator('.subnav').getByRole('button', { name: 'Stock', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText('Loading…')).toHaveCount(0);
  await page.unroute('**/api/v1/stock');
  await page.getByRole('alert').getByRole('button', { name: 'Reload' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('.subnav').getByRole('button', { name: 'Stock', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByRole('heading', { name: 'Stock', exact: true })).toBeVisible();
  await expect(row(page, 'Milk')).toContainText('Not counted');
  await shot(page, '10-stock-list');

  // ---- Opening count: 3 packets + 200 ml = 1.7 L, once only ----
  await row(page, 'Milk').click();
  await sheet(page).getByRole('button', { name: 'Enter opening count' }).click();
  await plus(page, 'packet', 3);
  await sheet(page).getByLabel('Loose (ml)').fill('200');
  await expect(sheet(page).getByRole('button', { name: 'Save count: 1.7 L' })).toBeVisible();
  await shot(page, '11-opening-count');
  await sheet(page).getByRole('button', { name: 'Save count: 1.7 L' }).click();
  await expect(sheet(page)).toContainText('1.7 L on hand');
  await expect(sheet(page).getByRole('button', { name: 'Enter opening count' })).toHaveCount(0);

  // ---- Stock in 2 packets: 2.7 L ----
  await sheet(page).getByRole('button', { name: 'Stock in' }).click();
  await plus(page, 'packet', 2);
  await sheet(page).getByLabel('Paid (₹, optional)').fill('56');
  await sheet(page).getByRole('button', { name: 'Add 1 L' }).click();
  await expect(sheet(page)).toContainText('2.7 L on hand');
  await expect(sheet(page).locator('.ledger li')).toHaveCount(2);
  await shot(page, '12-milk-history');
  await sheet(page).getByRole('button', { name: 'Close' }).click();
  await expect(row(page, 'Milk')).not.toContainText('Not counted');

  // ---- Log one decoction batch: takes 2 L of milk (2.7 -> 0.7 L = 700 ml) ----
  await page.getByRole('button', { name: 'Log 1 batch' }).click();
  await expect(page.getByRole('status')).toContainText('Logged: 1 batch of Tea decoction (2.2 L)');
  await expect(row(page, 'Milk')).toContainText('700 ml');
  await shot(page, '13-after-batch');

  // ---- Tablet layout ----
  await page.setViewportSize({ width: 1280, height: 800 });
  await row(page, 'Milk').click();
  await shot(page, '14-tablet-sheet');
  await page.keyboard.press('Escape');
  // Tablets: Manage's sections are a sidebar in three groups.
  const nav = page.getByRole('navigation', { name: 'Manage' });
  await expect(nav.getByRole('group', { name: 'Money' })).toBeVisible();
  const navBox = await nav.boundingBox();
  expect(navBox!.width).toBeLessThan(260);
  await shot(page, '15-tablet-manage');
});

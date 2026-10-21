/**
 * The owner's quick reads, end to end on a phone: search the menu on the till,
 * see this week against last on Sales, and Manage's stock bars. Screenshots for review.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection, saveAndPrint } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });

test('owner: menu search, this week against last, stock bars', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E insights phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // ---- Search looks across every category, highlights, and clears ----
  const tiles = page.locator('.tile');
  await expect(tiles.first()).toBeVisible();
  await page.getByLabel('Search the menu').fill('JUI');
  await expect(tiles).toHaveCount(1);
  await expect(tiles.first()).toContainText('Orange juice');
  await expect(page.locator('.tile-name mark')).toHaveText('jui');
  await expect(page.getByRole('status').filter({ hasText: 'match' })).toContainText('1 item match “JUI”');
  await shot(page, 'insights-1-search');
  await page.getByLabel('Search the menu').fill('zzz');
  await expect(page.getByText('Nothing on the menu matches “zzz”')).toBeVisible();
  await page.getByRole('button', { name: 'Clear search' }).click();
  await expect(page.locator('.categories')).toBeVisible();

  // ---- A bill today, so Sales has something to put beside last week ----
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click(); // the bill sheet opens from the bar
  await saveAndPrint(page);
  await page.getByRole('dialog').getByRole('button', { name: 'New bill', exact: true }).click();

  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await openSection(page, 'Sales');
  const compare = page.getByRole('region', { name: 'Compared with last week' });
  await expect(compare).toBeVisible();
  await expect(compare).toContainText('Today so far'); // a part-day gets no percentage
  await shot(page, 'insights-2-sales');

  // ---- Stock: bars against the reorder level, three ways to order ----
  await openSection(page, 'Stock');
  const order = page.getByRole('group', { name: 'Order the list' });
  await expect(order.getByRole('button', { name: 'Worst first' })).toHaveAttribute('aria-pressed', 'true');
  await order.getByRole('button', { name: 'A–Z' }).click();
  await expect(order.getByRole('button', { name: 'A–Z' })).toHaveAttribute('aria-pressed', 'true');
  await order.getByRole('button', { name: 'Low only' }).click();
  await shot(page, 'insights-3-stock');
});

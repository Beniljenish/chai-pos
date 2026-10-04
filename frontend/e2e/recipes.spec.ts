/**
 * Owner recipes (SOPs), end to end: edit a recipe, see its versions, sell, and
 * check the sale deducted by the NEW version. Plus packaging and new ingredients.
 */
import { expect, test, type Page } from '@playwright/test';
import { saveAndPrint } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

/** Phone layout guard (the top bar broke twice): the screen tabs sit in one
 * row at the bottom of the screen, and the top bar is a single row with the
 * sync badge in it. */
async function expectPhoneBars(page: Page) {
  const vh = page.viewportSize()?.height ?? 844;
  const tabs = await page.locator('.tabs').boundingBox();
  expect(tabs).not.toBeNull();
  expect(Math.abs(tabs!.y + tabs!.height - vh)).toBeLessThan(2); // pinned to the bottom
  expect(tabs!.height).toBeLessThan(90); // one row
  const bar = await page.locator('.topbar').boundingBox();
  const badge = await page.locator('.sync-badge').boundingBox();
  expect(bar!.height).toBeLessThan(80); // one row
  expect(badge!.y).toBeLessThan(bar!.y + bar!.height);
}
const sub = (page: Page, name: string) => page.locator('.subnav').getByRole('button', { name, exact: true });

test('owner recipes: new version is what the next sale deducts', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E recipes phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await tab(page, 'Manage').click();
  await expectPhoneBars(page);
  await sub(page, 'Recipes').click();
  await expect(page.getByRole('heading', { name: 'Recipes', exact: true })).toBeVisible();
  await expect(page.locator('.sop-list li', { hasText: 'Masala tea' })).toBeVisible();
  await shot(page, '20-recipes');

  // ---- Masala tea: decoction 100 ml -> 120 ml, saved as a new version ----
  await page.locator('.sop-list li', { hasText: 'Masala tea' }).click();
  await expect(sheet(page)).toContainText('Version 1');
  await sheet(page).getByLabel('Quantity of Tea decoction').fill('120');
  await shot(page, '21-recipe-edit');
  await sheet(page).getByRole('button', { name: 'Save as version 2' }).click();
  await expect(sheet(page)).toContainText('Version 2, since');
  await sheet(page).getByText(/History \(2 versions\)/).click();
  await expect(sheet(page).locator('.history li')).toHaveCount(2);
  await shot(page, '22-recipe-history');
  await sheet(page).getByRole('button', { name: 'Close' }).click();

  // ---- Juice yield is shown as the fruit per glass ----
  await page.locator('.sop-list li', { hasText: 'Orange juice' }).click();
  await expect(sheet(page)).toContainText('555.556 g of Oranges per glass');
  await sheet(page).getByRole('button', { name: 'Close' }).click();

  // ---- Packaging is marked; a new ingredient with a pack size ----
  const cup = page.locator('.ing-list li', { hasText: 'Paper cup' });
  await expect(cup.getByLabel('Same amount for every size (cups, lids, straws)')).toBeChecked();
  await page.getByRole('button', { name: '+ New ingredient' }).click();
  await page.getByLabel('Name').fill('Ginger');
  await page.getByRole('button', { name: 'Add ingredient' }).click();
  const ginger = page.locator('.ing-list li', { hasText: 'Ginger' });
  await expect(ginger).toContainText('No pack sizes yet');
  await ginger.getByRole('button', { name: '+ Pack size' }).click();
  await ginger.getByLabel('Pack name').fill('box');
  await ginger.getByLabel('Holds (g)').fill('500');
  await ginger.getByRole('button', { name: 'Add pack size' }).click();
  await expect(ginger).toContainText('Comes in: box (500 g)');
  await shot(page, '23-ingredients');

  // ---- Sell one tea: it must deduct 120 ml (version 2), not 100 ----
  await tab(page, 'New bill').click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await saveAndPrint(page);
  await page.getByRole('dialog').getByRole('button', { name: 'New bill', exact: true }).click();
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  await tab(page, 'Manage').click();
  await sub(page, 'Stock').click();
  await page.locator('.stock-list li', { hasText: 'Tea decoction' }).click();
  await expect(sheet(page).locator('.ledger li').first()).toContainText('Sold');
  await expect(sheet(page).locator('.ledger li').first()).toContainText('−120 ml');
});

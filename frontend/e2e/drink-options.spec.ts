/**
 * A brand new drink, end to end, as the owner does it on a phone: add it from
 * Recipes, give it a recipe, offer Large and a new option on it, then sell one
 * Large and check the stock went down by the scaled recipe.
 */
import { expect, test, type Page } from '@playwright/test';
import { saveAndPrint } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });
const sub = (page: Page, name: string) => page.locator('.subnav').getByRole('button', { name, exact: true });

test('new drink with its recipe and options, sold Large', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E options phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await tab(page, 'Manage').click();
  await sub(page, 'Recipes').click();

  // ---- + New drink goes straight on to its recipe ----
  await page.getByRole('button', { name: '+ New drink' }).click();
  await sheet(page).getByLabel('Name').fill('Tulsi tea');
  await sheet(page).getByLabel('Price (₹)').fill('25');
  await sheet(page).getByLabel('Large').check(); // offer an existing option from the drink's side
  await shot(page, '24-new-drink');
  await sheet(page).getByRole('button', { name: 'Next: the recipe' }).click();

  await expect(sheet(page).getByRole('heading', { name: 'Tulsi tea' })).toBeVisible();
  await expect(sheet(page)).toContainText('No recipe yet');
  await sheet(page).getByRole('button', { name: '+ Add ingredient' }).click();
  await sheet(page).getByLabel('Ingredient 1', { exact: true }).selectOption({ label: 'Tea decoction' });
  await sheet(page).getByLabel('Quantity of Tea decoction').fill('100');
  await sheet(page).getByRole('button', { name: 'Save as version 1' }).click();
  await expect(sheet(page)).toContainText('Version 1, since');
  await sheet(page).getByRole('button', { name: 'Close' }).click();
  await expect(page.locator('.sop-list li', { hasText: 'Tulsi tea' })).toContainText('Tea decoction 100 ml');

  // ---- Large is now on Tulsi tea; its preview shows the scaled recipe ----
  const large = page.locator('.opt-list li', { hasText: 'Large' });
  await expect(large).toContainText('Tulsi tea');
  await large.click();
  await sheet(page).getByLabel('One serving of').selectOption({ label: 'Tulsi tea' });
  await expect(sheet(page).locator('.opt-preview tr', { hasText: 'Tea decoction' })).toContainText('150 ml');
  await sheet(page).getByRole('button', { name: 'Close' }).click();

  // ---- A new option, offered from the option's side ----
  await page.getByRole('button', { name: '+ New option' }).click();
  await sheet(page).getByLabel('Name on the bill').fill('Extra sugar');
  await sheet(page).getByLabel('Price change in rupees').fill('2');
  await sheet(page).getByRole('button', { name: '+ Add ingredient change' }).click();
  await sheet(page).getByLabel('Ingredient 1', { exact: true }).selectOption({ label: 'Sugar' });
  await sheet(page).getByLabel('More or less Sugar').selectOption('more');
  await sheet(page).getByLabel('How much Sugar').fill('5');
  await sheet(page).getByRole('group', { name: 'Offered on' }).getByLabel('Tulsi tea').check();
  await expect(sheet(page).locator('.opt-preview tr', { hasText: 'Sugar' })).toContainText('5 g');
  await shot(page, '25-new-option');
  await sheet(page).getByRole('button', { name: 'Add option' }).click();
  const extra = page.locator('.opt-list li', { hasText: 'Extra sugar' });
  await expect(extra).toContainText('+₹2 · Sugar +5 g');
  await expect(extra).toContainText('On: Tulsi tea');
  await shot(page, '26-options-list');

  // ---- Sell one Large Tulsi tea: ₹35, and 150 ml of decoction ----
  await tab(page, 'New bill').click();
  await page.locator('.tile', { hasText: 'Tulsi tea' }).click();
  await page.locator('.till-handle').click();
  const line = page.locator('ul.lines li', { hasText: 'Tulsi tea' });
  await expect(line.getByRole('button', { name: 'Extra sugar +₹2' })).toBeVisible();
  await line.getByRole('button', { name: 'Large +₹10' }).click();
  await expect(line).toContainText('₹35');
  await saveAndPrint(page);
  await page.getByRole('dialog').getByRole('button', { name: 'New bill', exact: true }).click();
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  await tab(page, 'Manage').click();
  await sub(page, 'Stock').click();
  await page.locator('.stock-list li', { hasText: 'Tea decoction' }).click();
  await expect(sheet(page).locator('.ledger li').first()).toContainText('Sold');
  await expect(sheet(page).locator('.ledger li').first()).toContainText('−150 ml');
});

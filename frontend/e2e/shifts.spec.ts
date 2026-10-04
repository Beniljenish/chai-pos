/**
 * The cash drawer on a phone, end to end:
 *   start with Rs 500, sell one Rs 20 tea for cash and one for UPI, pay the
 *   milkman Rs 100 -> the drawer should hold 500 + 20 - 100 = Rs 420.
 *   Count 4 x Rs 100 + 1 x Rs 20 = Rs 420: matched (the counter never sees 420).
 *   Next shift starts from 420; counted 400 -> Rs 20 short.
 * Other specs bill on the same day, so the owner's report is read for this tablet.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const TABLET = 'E2E shifts phone';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

async function sellTea(page: Page, payment: 'Cash' | 'UPI') {
  await tab(page, 'New bill').click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('radio', { name: payment }).click();
  await page.getByRole('button', { name: 'Save and print' }).click();
  await sheet(page).getByRole('button', { name: 'New bill', exact: true }).click();
}

test('a shift from opening float to blind count; the owner sees whether it matched', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill(TABLET);
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // ---- The first bill asks for the opening cash; the bill then goes through ----
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Save and print' }).click();
  const start = page.getByRole('dialog', { name: 'Start shift' });
  await expect(start).toBeVisible();
  await start.getByLabel('Cash in the drawer now (₹)').fill('500');
  await shot(page, '50-start-shift');
  await start.getByRole('button', { name: 'Start shift with ₹500' }).click();
  await expect(sheet(page)).toContainText('₹20'); // the receipt
  await sheet(page).getByRole('button', { name: 'New bill', exact: true }).click();
  await sellTea(page, 'UPI');

  // ---- Paid out of the drawer ----
  await tab(page, 'Today').click();
  const panel = page.getByRole('region', { name: 'Cash drawer' });
  await expect(panel).toContainText('started with ₹500');
  await panel.getByRole('button', { name: 'Paid out' }).click();
  await sheet(page).getByLabel('Amount (₹)').fill('100');
  await sheet(page).getByRole('button', { name: 'Milk' }).click();
  await sheet(page).getByRole('button', { name: 'Save ₹100' }).click();
  await expect(sheet(page)).toHaveCount(0);

  // ---- End shift: a blind count by notes ----
  await panel.getByRole('button', { name: 'End shift' }).click();
  await sheet(page).getByLabel('₹100 notes').fill('4');
  await sheet(page).getByLabel('₹20 notes').fill('1');
  await expect(sheet(page)).toContainText('Counted: ₹420');
  await expect(sheet(page)).not.toContainText('Should be'); // never shown to the person counting
  await shot(page, '51-end-shift-count');
  await sheet(page).getByRole('button', { name: 'End shift with ₹420' }).click();
  await expect(sheet(page).getByRole('status')).toContainText('You counted ₹420');
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  await expect(panel).toContainText('No shift open');

  // ---- Next shift starts from the count; this one ends ₹20 short ----
  await panel.getByRole('button', { name: 'Start shift now' }).click();
  await expect(sheet(page).getByLabel('Cash in the drawer now (₹)')).toHaveValue('420');
  await sheet(page).getByRole('button', { name: 'Start shift with ₹420' }).click();
  await panel.getByRole('button', { name: 'End shift' }).click();
  await sheet(page).getByLabel('₹200 notes').fill('2');
  await sheet(page).getByRole('button', { name: 'End shift with ₹400' }).click();
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  // ---- Owner: Sales -> Cash drawer, this tablet's two shifts ----
  await tab(page, 'Manage').click();
  await openSection(page, 'Sales'); // a phone opens Manage on its list
  const mine = page.locator('.shift-list > li', { hasText: TABLET });
  await expect(mine).toHaveCount(2);
  const first = mine.nth(0);
  await expect(first).toContainText('Matched');
  await expect(first.locator('tr', { hasText: 'Started with' })).toContainText('₹500');
  await expect(first.locator('tr', { hasText: 'Cash sales' })).toContainText('₹20');
  await expect(first.locator('tr', { hasText: 'Paid out: Milk' })).toContainText('₹100');
  await expect(first.locator('tr', { hasText: 'Should be in the drawer' })).toContainText('₹420');
  await expect(first).toContainText('UPI ₹20');
  await expect(mine.nth(1)).toContainText('₹20 short');
  // One line per drawer: a matched one stays folded, a short one opens by itself.
  await expect(first.locator('details')).not.toHaveAttribute('open', '');
  await expect(first.locator('tr', { hasText: 'Started with' })).toBeHidden();
  await expect(mine.nth(1).locator('details')).toHaveAttribute('open', '');
  await first.locator('summary').click();
  await expect(first.locator('tr', { hasText: 'Started with' })).toBeVisible();
  await mine.nth(0).scrollIntoViewIfNeeded();
  await shot(page, '52-cash-drawer-report');
});

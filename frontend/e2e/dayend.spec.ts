/**
 * Day end in a real browser: wastage, the owner reconciling against the balance, the
 * owner's variance report and approval; and the cashier's restricted view.
 * Today's count is left unapproved so later specs' sales are unaffected; the
 * approval is exercised on yesterday (a quiet day: everything exact).
 */
import { expect, test, type Page } from '@playwright/test';
import { saveAndPrint, openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const CASHIER = process.env.E2E_CASHIER ?? '9000000002';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

async function login(page: Page, phone: string, tablet: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(phone);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  if (phone === OWNER) {
    await page.getByLabel('Tablet name').fill(tablet);
    await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  }
}

test('owner: wastage, reconcile against the balance, variance, approval', async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, OWNER, 'E2E dayend phone');

  // Two teas sold today, so decoction has usage the count can disagree with.
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await saveAndPrint(page);
  await page.getByRole('dialog').getByRole('button', { name: 'New bill', exact: true }).click();
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });

  await tab(page, 'Manage').click();
  // One decoction batch (+2.2 L) before counting: counting zero is then ~2.2 L
  // short, far outside tolerance however many teas the other specs sold today.
  await openSection(page, 'Stock');
  await page.getByRole('button', { name: 'Log 1 batch' }).click();
  await expect(page.getByRole('status')).toContainText('Logged: 1 batch of Tea decoction');
  await openSection(page, 'Day end');
  await expect(page.getByRole('heading', { name: 'Day end' })).toBeVisible();

  // ---- Wastage: one tea spilled ----
  const w = page.locator('.wastage');
  await w.getByLabel('Which drink').selectOption({ label: 'Masala tea' });
  await w.getByRole('radio', { name: 'Spilled / dropped' }).click();
  await w.getByRole('button', { name: 'Record wastage' }).click();
  await expect(w.getByRole('status')).toContainText('Recorded: 1 × Masala tea, spilled / dropped');

  // ---- Owner count: the balance is shown; "Matches" or the real amount ----
  const count = page.locator('.count');
  const decoctionRow = count.locator('.count-list li', { hasText: 'Tea decoction' });
  await expect(decoctionRow).toContainText('Should be');
  const zeros = count.getByRole('button', { name: 'It is zero' });
  const n = await zeros.count();
  for (let i = 0; i < n; i++) await zeros.nth(i).click();
  await expect(decoctionRow).toContainText('vs balance'); // zero on the shelf, record says otherwise
  await shot(page, '40-owner-count');
  await count.getByRole('button', { name: 'Send count' }).click();
  // No "count again" for the owner: it goes straight to the report.
  await expect(count.getByRole('status')).toContainText('Count sent to the owner');
  await expect(count.getByRole('button', { name: 'Count again' })).toBeVisible();

  // ---- The owner's variance report ----
  const report = page.locator('.report');
  const decoction = report.locator('.variance-list li', { hasText: 'Tea decoction' });
  await expect(decoction).toContainText('Check');
  await decoction.locator('summary').click();
  await expect(decoction).toContainText('− Sold (by recipe)');
  await expect(decoction).toContainText('− Wasted');
  await shot(page, '42-variance');
  await expect(report.getByRole('button', { name: 'Approve and close the day' })).toBeVisible();

  // ---- Approve yesterday (quiet: all exact) ----
  await page.getByRole('radio', { name: /^Yesterday/ }).click();
  // Wait for yesterday's sheet to load (today's sent count shows no list).
  await expect(count.getByRole('button', { name: 'It is zero' }).first()).toBeVisible();
  const zerosY = count.getByRole('button', { name: 'It is zero' });
  const k = await zerosY.count();
  for (let i = 0; i < k; i++) await zerosY.nth(i).click();
  await count.getByRole('button', { name: 'Send count' }).click();
  await expect(count.getByRole('status')).toContainText('Count sent to the owner');
  await report.getByRole('button', { name: 'Approve and close the day' }).click();
  await report.getByRole('button', { name: 'Yes, close the day' }).click();
  await expect(report).toContainText('Closed by');
  await expect(count).toContainText('This day is closed');
  await shot(page, '43-closed');
});

test('cashier: batches, wastage and a blind count; no rupees, no report', async ({ page }) => {
  // The owner sets the tablet up once; then the cashier works on it.
  await login(page, OWNER, 'E2E counter for cashier');
  await page.getByRole('button', { name: 'Log out' }).click();
  await page.getByLabel('Mobile number').fill(CASHIER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.locator('.where')).toContainText('Cashier');

  await tab(page, 'Stock').click();
  await expect(page.getByRole('heading', { name: 'Stock tasks' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Made a batch?' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Something wasted?' })).toBeVisible();
  // Blind: no balances, no variance report, no rupees, no owner-only reasons.
  const count = page.locator('.count');
  await expect(count).toBeVisible();
  await count.getByRole('button', { name: 'Count again' }).click(); // the owner already sent one today
  await expect(count.getByRole('button', { name: 'It is zero' }).first()).toBeVisible();
  await expect(count).not.toContainText('Should be');
  await expect(count.getByRole('button', { name: /matches the balance/ })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Variance' })).toHaveCount(0);
  await expect(page.locator('main')).not.toContainText('₹');
  await page.locator('.wastage').getByLabel('Which drink').selectOption({ label: 'Masala tea' });
  await expect(page.getByRole('radio', { name: 'Free (on the house)' })).toHaveCount(0);
  await expect(page.getByRole('radio', { name: 'Theft / unexplained' })).toHaveCount(0);
  await shot(page, '44-cashier-stock');

  // ---- Cashier's blind count: items that moved come back once, with no numbers ----
  const zeros = count.getByRole('button', { name: 'It is zero' });
  const n = await zeros.count();
  for (let i = 0; i < n; i++) await zeros.nth(i).click();
  await count.getByRole('button', { name: 'Send count' }).click();
  await expect(count.getByRole('heading', { name: 'Please count these again' })).toBeVisible();
  await expect(count.locator('.count-list li', { hasText: 'Tea decoction' })).toBeVisible();
  await expect(count).not.toContainText('vs balance');
  await shot(page, '45-cashier-recount');
  const again = count.getByRole('button', { name: 'It is zero' });
  const m = await again.count();
  for (let i = 0; i < m; i++) await again.nth(i).click();
  await count.getByRole('button', { name: 'Send recount' }).click();
  await expect(count.getByRole('status')).toContainText('Count sent to the owner');
});

test('phase 10: adherence trend, a large wastage for the owner, a handover count', async ({ page }) => {
  test.setTimeout(180_000);
  const sheet = () => page.getByRole('dialog');
  await login(page, OWNER, 'E2E phase 10 phone');

  // ---- 10.1: the trend sits under the day's report ----
  await tab(page, 'Manage').click();
  await openSection(page, 'Day end');
  await expect(page.getByRole('heading', { name: 'Recipe adherence, last 30 days' })).toBeVisible();

  // ---- 10.2: any cashier wastage now waits for the owner ----
  const pending = page.locator('.pending-wastage');
  await pending.getByLabel("Ask me when a cashier's wastage is over (₹)").fill('0');
  await pending.getByRole('button', { name: 'Save' }).click();
  await expect(pending.getByRole('button', { name: 'Save' })).toBeDisabled();
  await shot(page, '46-wastage-limit');

  await page.getByRole('button', { name: 'Log out' }).click();
  await page.getByLabel('Mobile number').fill(CASHIER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await tab(page, 'Stock').click();
  const w = page.locator('.wastage');
  await w.getByLabel('Which drink').selectOption({ label: 'Masala tea' });
  await w.getByRole('radio', { name: 'Spilled / dropped' }).click();
  await w.getByRole('button', { name: 'Record wastage' }).click();
  await expect(w.getByRole('status')).toContainText('Recorded: 1 × Masala tea');
  await w.locator('details.history summary').click();
  await expect(w.locator('.ledger li', { hasText: 'Masala tea' }).first()).toContainText('Waiting for the owner');
  await expect(page.locator('main')).not.toContainText('₹'); // still blind to rupees

  await page.getByRole('button', { name: 'Log out' }).click();
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await tab(page, 'Manage').click();
  await openSection(page, 'Day end');
  const waiting = pending.locator('.ledger li', { hasText: 'Masala tea' });
  await expect(waiting).toContainText('₹');
  await shot(page, '47-wastage-to-check');
  await waiting.getByRole('button', { name: 'Reject' }).click();
  await expect(pending).toContainText('Nothing waiting for you.');

  // ---- 10.3: milk is counted at each shift change ----
  await openSection(page, 'Stock');
  await page.locator('.stock-list li', { hasText: 'Milk' }).click();
  await sheet().getByRole('radio', { name: 'Every shift' }).click();
  await expect(sheet()).toContainText('Counted at each shift change');
  await sheet().getByRole('button', { name: 'Close' }).click();

  await tab(page, 'Today').click();
  const panel = page.getByRole('region', { name: 'Cash drawer' });
  await panel.getByRole('button', { name: 'Start shift now' }).click();
  await sheet().getByLabel('Cash in the drawer now (₹)').fill('500');
  await sheet().getByRole('button', { name: 'Start shift with ₹500' }).click();
  await panel.getByRole('button', { name: 'End shift' }).click();
  const handover = sheet().locator('.handover');
  await expect(handover).toContainText('Milk');
  await expect(sheet().getByRole('button', { name: /End shift with/ })).toBeDisabled(); // stock first
  await expect(handover).not.toContainText('Should be'); // blind
  await handover.getByLabel('Loose (ml)').fill('1000');
  await shot(page, '48-handover-count');
  await handover.getByRole('button', { name: 'Send count' }).click();
  await expect(sheet()).toContainText('Milk and fruit counted');
  await sheet().getByLabel('₹500 notes').fill('1');
  await sheet().getByRole('button', { name: 'End shift with ₹500' }).click();
  await sheet().getByRole('button', { name: 'Done' }).click();

  await tab(page, 'Manage').click();
  await openSection(page, 'Day end');
  const periods = page.locator('.handover-report');
  await expect(periods.getByRole('heading', { name: 'Shift handovers' })).toBeVisible();
  await expect(periods.locator('.period-lines li', { hasText: 'Milk' }).first()).toBeVisible();
  await shot(page, '49-shift-handovers');
});

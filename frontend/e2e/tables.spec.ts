/**
 * Table service on a waiter's phone: a table orders in two rounds (two KOTs), one
 * item is cancelled with a reason, the bill is printed at the table, and the
 * table pays: one tax invoice, the table is free again. Then a takeaway.
 * Printing goes through RawBT so the test can read every ticket.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });
const sub = (page: Page, name: string) => page.locator('.subnav').getByRole('button', { name, exact: true });

async function lastPrinted(page: Page): Promise<string> {
  return page.evaluate(() => {
    const prints = (window as unknown as { __prints: string[] }).__prints;
    const bytes = atob((prints[prints.length - 1] ?? '').replace('rawbt:base64,', ''));
    // eslint-disable-next-line no-control-regex
    return bytes.replace(/\x1b@|\x1b[aEd][\s\S]|\x1d![\s\S]|\x1dV[\s\S][\s\S]/g, '').replace(/[^\x20-\x7e\n]/g, '');
  });
}
const printCount = (page: Page) => page.evaluate(() => (window as unknown as { __prints: string[] }).__prints.length);

test('a table orders in rounds, gets its bill, and pays', async ({ page }) => {
  test.setTimeout(120_000);
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
  await page.getByLabel('Tablet name').fill('E2E waiter phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // ---- This phone prints through RawBT ----
  await tab(page, 'Today').click();
  await page.getByRole('button', { name: 'Printer', exact: true }).click();
  await sheet(page).getByLabel(/RawBT app/).check();
  await expect(sheet(page).getByLabel(/kitchen ticket/)).toBeChecked();
  await sheet(page).getByRole('button', { name: 'Done' }).click();

  // ---- Its own area, so the spec does not depend on others ----
  await tab(page, 'Manage').click();
  await sub(page, 'Floor').click();
  await page.getByRole('button', { name: '+ Area' }).click();
  await sheet(page).getByLabel('Name', { exact: true }).fill('Family');
  await sheet(page).getByRole('button', { name: 'Add area' }).click();
  const family = page.locator('.area-card', { hasText: 'Family' });
  await family.getByRole('button', { name: 'Add tables to Family' }).click();
  await sheet(page).getByLabel('How many').fill('2');
  await sheet(page).getByLabel('Name starts with').fill('F');
  await sheet(page).getByRole('button', { name: 'Add 2 tables' }).click();
  await expect(family).toContainText('2 tables');

  // ---- The floor: on a phone the four tabs and the sync badge still fit one row ----
  await tab(page, 'Tables').click();
  await expect(page.getByRole('heading', { name: 'Tables' })).toBeVisible();
  const tabsBox = await page.locator('.tabs').boundingBox();
  const badgeBox = await page.locator('.sync-badge').boundingBox();
  expect(Math.abs((tabsBox?.y ?? 0) - (badgeBox?.y ?? 100))).toBeLessThan(12);
  const f1 = page.getByRole('region', { name: 'Family' }).getByRole('button', { name: /^Table F1,/ });
  await expect(f1).toHaveAccessibleName('Table F1, free');
  await shot(page, '90-floor');

  // ---- Round one: two teas, one large with a note ----
  await f1.click();
  await expect(page.getByRole('heading', { name: 'F1' })).toBeVisible();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.getByRole('button', { name: 'Guests' }).click();
  await sheet(page).getByRole('group', { name: 'Guests' }).getByRole('button', { name: '3', exact: true }).click();
  await sheet(page).getByRole('button', { name: 'Save' }).click();
  await expect(page.locator('.order-title')).toContainText('3 guests');
  await expect(page.locator('.till-handle')).toContainText('2 new, not sent');
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Note' }).click();
  await page.getByLabel('Note for the kitchen: Masala tea').fill('less sugar');
  await shot(page, '91-order-round');
  await page.getByRole('button', { name: 'Send to kitchen (2)' }).click();

  const kot = page.getByRole('dialog', { name: /^KOT / });
  await expect(kot).toBeVisible();
  await expect.poll(() => printCount(page)).toBe(1);
  let printed = await lastPrinted(page);
  for (const words of ['KOT ', 'F1', 'Guests: 3', '2   Masala tea', '* less sugar']) expect(printed).toContain(words);
  expect(printed).not.toContain('Rs.');
  await shot(page, '92-kot');
  await kot.getByRole('button', { name: 'Done' }).click();

  // Back on the floor: F1 is eating, ₹40, with a note that the KOT went.
  await expect(page.locator('.floor-notice')).toContainText('sent for F1');
  await expect(f1).toHaveClass(/running/);
  await expect(f1).toContainText('₹40');

  // ---- Round two: an orange juice ----
  await f1.click();
  await page.getByRole('button', { name: 'Juice', exact: true }).click();
  await page.locator('.tile', { hasText: 'Orange juice' }).click();
  await page.locator('.till-handle').click();
  await expect(page.locator('.till')).toContainText('Ordered');
  await page.getByRole('button', { name: 'Send to kitchen (1)' }).click();
  await expect.poll(() => printCount(page)).toBe(2);
  expect(await lastPrinted(page)).toContain('1   Orange juice');
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  await expect(f1).toContainText('₹100');

  // ---- One tea is cancelled: a reason is required; the kitchen gets a cancel ticket ----
  await f1.click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Cancel Masala tea' }).click();
  const cancel = page.getByRole('dialog', { name: 'Cancel Masala tea' });
  await expect(cancel.getByRole('button', { name: 'Cancel 1 Masala tea' })).toBeDisabled();
  await cancel.getByRole('button', { name: 'Customer changed mind' }).click();
  await cancel.getByRole('button', { name: 'Cancel 1 Masala tea' }).click();
  await expect.poll(() => printCount(page)).toBe(3);
  printed = await lastPrinted(page);
  for (const words of ['CANCEL', '-1  Masala tea', 'Reason: Customer changed mind']) expect(printed).toContain(words);
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  // The cancel ticket keeps the order open on screen.
  await expect(page.locator('.till')).toContainText('1 cancelled');
  await expect(page.locator('.till .total')).toContainText('₹80');

  // ---- The bill at the table: total, no invoice number ----
  await page.getByRole('button', { name: 'Print bill' }).click();
  await expect.poll(() => printCount(page)).toBe(4);
  printed = await lastPrinted(page);
  for (const words of ['BILL', 'F1', 'Guests 3', 'TOTAL', 'Rs.80', 'Please pay']) expect(printed).toContain(words);
  expect(printed).not.toMatch(/^No\./m);
  await shot(page, '93-bill-at-table');
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  await expect(f1).toHaveClass(/billed/);

  // ---- The table pays by UPI: one invoice, and the table is free ----
  await f1.click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Settle', exact: true }).click();
  const settle = page.getByRole('dialog', { name: 'Settle F1' });
  await expect(settle).toContainText('₹80');
  await settle.getByRole('radio', { name: 'UPI' }).click();
  await shot(page, '94-settle');
  await settle.getByRole('button', { name: 'Settle and print receipt' }).click();
  const start = page.getByRole('dialog', { name: 'Start shift' });
  if (await start.isVisible()) {
    await start.getByLabel('Cash in the drawer now (₹)').fill('500');
    await start.getByRole('button', { name: /^Start shift/ }).click();
  }
  const receipt = page.getByRole('dialog', { name: /^Bill / });
  await expect(receipt).toBeVisible();
  const invoice = ((await receipt.getAttribute('aria-label')) ?? '').replace('Bill ', '');
  await expect.poll(async () => (await lastPrinted(page)).includes(invoice)).toBe(true);
  printed = await lastPrinted(page);
  for (const words of ['Masala tea', 'Orange juice', 'Rs.80', 'Paid by', 'UPI']) expect(printed).toContain(words);
  await receipt.getByRole('button', { name: 'Back to tables' }).click();
  await expect(page.locator('.floor-notice')).toContainText(`F1 settled: ${invoice}`);
  await expect(f1).toHaveAccessibleName('Table F1, free');

  // The invoice is an ordinary bill under Today, and it reaches the server.
  await tab(page, 'Today').click();
  await expect(page.locator('.bill-list li', { hasText: invoice })).toContainText('₹80');
  await expect(page.locator('.sync-badge')).toHaveAccessibleName(/All bills sent/, { timeout: 20_000 });

  // ---- A takeaway: started from the floor, then cancelled with a reason ----
  await tab(page, 'Tables').click();
  await page.getByRole('button', { name: '+ Takeaway' }).click();
  await sheet(page).getByLabel(/Customer name/).fill('Priya');
  await sheet(page).getByRole('button', { name: 'Start order' }).click();
  await expect(page.getByRole('heading', { name: 'Takeaway: Priya' })).toBeVisible();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Send to kitchen (1)' }).click();
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  const takeaway = page.locator('.order-list li', { hasText: 'Takeaway: Priya' });
  await expect(takeaway).toContainText('₹20');
  await shot(page, '95-floor-with-takeaway');
  await takeaway.getByRole('button').click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Cancel order' }).click();
  await sheet(page).getByRole('button', { name: 'Taking too long' }).click();
  await sheet(page).getByRole('button', { name: 'Cancel order' }).click();
  await expect(sheet(page)).toContainText('CANCEL ALL');
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  await expect(page.locator('.floor-notice')).toContainText('Takeaway: Priya: order cancelled');
  await expect(page.locator('.order-list li', { hasText: 'Priya' })).toHaveCount(0);
});

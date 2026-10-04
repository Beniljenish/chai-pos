/**
 * Phase 6 on a phone: a bill discount with a reason, a split payment (cash +
 * UPI), a bill on credit with part paid now, the customer repaying some of it at
 * the counter, the owner's Khata and Sales; and a takeaway split into two bills.
 * Tickets print through RawBT so no print dialog is in the way.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

async function startShiftIfAsked(page: Page) {
  const start = page.getByRole('dialog', { name: 'Start shift' });
  await expect(page.getByRole('dialog').first()).toBeVisible();
  if (await start.isVisible()) {
    await start.getByLabel('Cash in the drawer now (₹)').fill('500');
    await start.getByRole('button', { name: /^Start shift/ }).click();
  }
}

test('discount, split payment, credit and the khata', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E phase 6 phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await tab(page, 'Today').click();
  await page.getByRole('button', { name: 'Printer', exact: true }).click();
  await sheet(page).getByLabel(/RawBT app/).check();
  await sheet(page).getByRole('button', { name: 'Done' }).click();

  // ---- Two teas, 5 rupees off the bill, paid 15 cash + 15 UPI ----
  await tab(page, 'New bill').click();
  const tea = page.locator('.tile', { hasText: 'Masala tea' });
  await tea.click();
  await tea.click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Discount', exact: true }).click();
  const disc = page.getByRole('dialog', { name: 'Discount' });
  await disc.getByLabel('Take it off').selectOption('bill');
  await disc.getByLabel('Amount off (₹)').fill('5');
  await expect(disc.getByRole('button', { name: 'Take off ₹5' })).toBeDisabled(); // a reason first
  await disc.getByRole('button', { name: 'Regular customer' }).click();
  await disc.getByRole('button', { name: 'Take off ₹5' }).click();
  await expect(page.locator('.till .total')).toContainText('₹35');
  await page.getByRole('radio', { name: 'Split' }).click();
  const split = page.getByRole('dialog', { name: 'Split ₹35' });
  await split.getByLabel('Cash (₹)').fill('15');
  await expect(split.getByRole('status')).toContainText('Cash ₹15 + UPI ₹20');
  await split.getByRole('button', { name: 'Split', exact: true }).click();
  await expect(page.locator('.payment-note')).toContainText('Cash ₹15 + UPI ₹20');
  await shot(page, '100-till-discount-split');
  await page.getByRole('button', { name: 'Save and print' }).click();
  await startShiftIfAsked(page);
  let receipt = page.getByRole('dialog', { name: /^Bill / });
  await expect(receipt).toContainText('Discount (Regular customer)');
  await expect(receipt).toContainText('Paid by Cash');
  await expect(receipt).toContainText('Paid by UPI');
  await receipt.getByRole('button', { name: 'New bill', exact: true }).click();

  // ---- An orange juice on Lakshmi's khata, 10 paid now in cash ----
  await page.locator('.categories').getByRole('button', { name: 'Juice', exact: true }).click();
  await page.locator('.tile', { hasText: 'Orange juice' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('radio', { name: 'Credit' }).click();
  const credit = page.getByRole('dialog', { name: 'On credit: ₹60' });
  await credit.getByLabel('Phone').fill('9123400077');
  await credit.getByLabel('Name').fill('Lakshmi');
  await credit.getByLabel(/Paid now in cash/).fill('10');
  await expect(credit.getByRole('status').last()).toContainText("₹50 goes on Lakshmi's khata");
  await shot(page, '101-credit');
  await credit.getByRole('button', { name: 'Put on credit' }).click();
  await expect(page.locator('.payment-note')).toContainText("₹50 on Lakshmi's khata, ₹10 cash now");
  await page.getByRole('button', { name: 'Save and print' }).click();
  receipt = page.getByRole('dialog', { name: /^Bill / });
  await expect(receipt).toContainText('On credit (khata)');
  await expect(receipt).toContainText('Lakshmi');
  await receipt.getByRole('button', { name: 'New bill', exact: true }).click();
  await expect(page.locator('.sync-badge')).toHaveAccessibleName(/All bills sent/, { timeout: 20_000 });

  // ---- Lakshmi repays 20 at the counter ----
  await tab(page, 'Today').click();
  await page.getByRole('button', { name: 'Customers', exact: true }).click();
  await sheet(page).getByLabel('Phone or name').fill('Laksh');
  await sheet(page).getByRole('button', { name: /Lakshmi/ }).click();
  const cust = page.getByRole('dialog', { name: 'Lakshmi' });
  await expect(cust.locator('.khata-owed')).toContainText('₹50');
  await cust.getByLabel('Amount (₹)').fill('20');
  await cust.getByRole('button', { name: 'Receive ₹20' }).click();
  await expect(cust.locator('.khata-owed')).toContainText('₹30');
  await shot(page, '102-customer-repaid');
  await cust.getByRole('button', { name: 'Close' }).click();

  // ---- The owner: Khata and Sales ----
  await tab(page, 'Manage').click();
  await openSection(page, 'Khata');
  await expect(page.locator('.khata-list li', { hasText: 'Lakshmi' })).toContainText('₹30');
  await openSection(page, 'Sales');
  const dc = page.getByRole('region', { name: 'Discounts and credit' });
  await expect(dc).toContainText('Regular customer');
  await expect(dc).toContainText('₹50 given on credit');
  await expect(dc).toContainText('₹20 repaid');
  await shot(page, '103-sales-discounts-credit');
});

test('a takeaway split into two bills', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E split phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await tab(page, 'Today').click();
  await page.getByRole('button', { name: 'Printer', exact: true }).click();
  await sheet(page).getByLabel(/RawBT app/).check();
  await sheet(page).getByRole('button', { name: 'Done' }).click();

  await tab(page, 'Tables').click();
  await page.getByRole('button', { name: '+ Takeaway' }).click();
  await sheet(page).getByLabel(/Customer name/).fill('Ravi and Anu');
  await sheet(page).getByRole('button', { name: 'Start order' }).click();
  const tea = page.locator('.tile', { hasText: 'Masala tea' });
  for (let i = 0; i < 3; i++) await tea.click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Send to kitchen (3)' }).click();
  await sheet(page).getByRole('button', { name: 'Done' }).click();

  await page.locator('.order-list li', { hasText: 'Ravi and Anu' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Settle', exact: true }).click();
  await sheet(page).getByRole('button', { name: 'Split bill' }).click();
  const split = page.getByRole('dialog', { name: 'Split bill' });
  await expect(split.getByRole('button', { name: 'Every bill needs an item' })).toBeDisabled();
  await split.getByRole('button', { name: 'One Masala tea to bill 2' }).click();
  await split.getByRole('group', { name: 'Bill 2 paid by' }).getByRole('button', { name: 'UPI' }).click();
  await expect(split.locator('.split-parts li').nth(0)).toContainText('₹40');
  await expect(split.locator('.split-parts li').nth(1)).toContainText('₹20');
  await shot(page, '104-split-bill');
  await split.getByRole('button', { name: 'Settle 2 bills and print' }).click();
  await startShiftIfAsked(page);
  const first = page.getByRole('dialog', { name: /^Bill / });
  await expect(first).toContainText('₹40');
  await first.getByRole('button', { name: 'Back to tables' }).click();
  const second = page.getByRole('dialog', { name: /^Bill / });
  await expect(second).toContainText('₹20');
  await expect(second).toContainText('UPI');
  await second.getByRole('button', { name: 'Back to tables' }).click();
  await expect(page.locator('.floor-notice')).toContainText('(split)');
  await expect(page.locator('.order-list li', { hasText: 'Ravi and Anu' })).toHaveCount(0);
  // The settle must reach the server before this page closes. Otherwise the
  // order stays open there, and its KOT shows in the next spec's kitchen.
  await expect(page.locator('.sync-badge')).toHaveAccessibleName(/All bills sent/, { timeout: 20_000 });
});

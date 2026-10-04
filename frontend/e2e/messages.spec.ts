/**
 * Customer messages: a takeaway whose customer agreed to messages is marked ready
 * in the kitchen, and "your order is ready" appears in the owner's Messages
 * screen with the number masked. CI's server has no Inkbox key, so the message is
 * written there and not sent (backend/tests/test_messages.py covers sending).
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });

test('a takeaway customer who agreed hears that the order is ready', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E messages phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // Tickets print through RawBT (nothing to click in a print dialog).
  await tab(page, 'Today').click();
  await page.getByRole('button', { name: 'Printer', exact: true }).click();
  await sheet(page).getByLabel(/RawBT app/).check();
  await sheet(page).getByRole('button', { name: 'Done' }).click();

  await tab(page, 'Tables').click();
  await page.getByRole('button', { name: '+ Takeaway' }).click();
  await sheet(page).getByLabel(/Customer name/).fill('Meena');
  const consent = sheet(page).getByLabel(/agrees to get the receipt/);
  await expect(consent).toHaveCount(0); // no number yet: nothing to agree to
  await sheet(page).getByLabel(/^Phone/).fill('9876501234');
  await expect(consent).not.toBeChecked(); // off by default
  await consent.check();
  await shot(page, '98-takeaway-consent');
  await sheet(page).getByRole('button', { name: 'Start order' }).click();
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await page.getByRole('button', { name: 'Send to kitchen (1)' }).click();
  await sheet(page).getByRole('button', { name: 'Done' }).click();

  const view = page.getByRole('group', { name: 'View' });
  await view.getByRole('button', { name: /^Kitchen/ }).click();
  await page.locator('.kitchen-ticket', { hasText: 'Meena' }).getByRole('button', { name: 'All ready' }).click();
  await view.getByRole('button', { name: 'Floor' }).click();
  await expect(page.locator('.sync-badge')).toHaveAccessibleName(/All bills sent/, { timeout: 20_000 });

  await tab(page, 'Manage').click();
  await openSection(page, 'Messages');
  await expect(page.getByText(/Sending is not set up yet/)).toBeVisible();
  const msg = page.locator('.message-list li', { hasText: 'Meena' });
  await expect(msg).toContainText('Order ready');
  await expect(msg).toContainText('••••••1234');
  await expect(msg).toContainText('Not sent (no provider)');
  await expect(page.locator('.message-list')).not.toContainText('9876501234');
  await shot(page, '99-messages');
});

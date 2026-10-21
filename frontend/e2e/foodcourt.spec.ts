/**
 * A food court, end to end in real browsers against the real API: the owner starts
 * a court and opens for orders; a customer with no login scans the link, orders and
 * follows the token; the outlet sees it on its Tables screen, marks it ready, and
 * the customer's page says so. Screenshots for review.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const phone = { width: 390, height: 844 };

test('a customer orders from a food court outlet and follows it to ready', async ({ page, browser }) => {
  test.setTimeout(120_000);
  await page.setViewportSize(phone);

  // ---- the outlet owner starts the court and opens for orders
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E food court counter');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await page.locator('.subnav').getByRole('button', { name: 'Food court', exact: true }).click();
  await page.getByLabel('Name customers will see').fill('E2E Food Court');
  await page.getByRole('button', { name: 'Create food court' }).click();
  const taking = page.getByRole('switch', { name: 'Taking online orders' });
  await expect(taking).toHaveAttribute('aria-checked', 'false'); // off until the outlet says so
  await taking.click();
  await expect(taking).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByLabel('QR code for the food court')).toBeVisible();
  await expect(page.getByLabel('Join code')).toHaveText(/^[A-Z2-9]{8}$/);
  const link = (await page.locator('.fc-qr-card code').textContent()) ?? '';
  expect(link).toMatch(/\/order\/e2e-food-court-[0-9a-f]{4}$/);
  await shot(page, 'foodcourt-1-owner');

  // ---- a customer, with no login and no staff app, scans the QR
  const customer = await (await browser.newContext({ viewport: phone })).newPage();
  await customer.goto(link);
  await expect(customer.getByRole('heading', { name: 'E2E Food Court' })).toBeVisible();
  await expect(customer.getByLabel('Log in')).toHaveCount(0);
  await shot(customer, 'foodcourt-2-outlets');
  await customer.getByRole('button', { name: /Open/ }).first().click();
  await customer.getByLabel('Add Masala tea').click();
  await customer.getByLabel('Add one more Masala tea').click();
  await customer.getByLabel('Add Orange juice').click();
  await expect(customer.getByText('3 items · ₹100')).toBeVisible(); // 2 × ₹20 + ₹60
  await shot(customer, 'foodcourt-3-menu');
  await customer.getByRole('button', { name: 'View order' }).click();

  await customer.getByLabel('Your name').fill('Ravi');
  await customer.getByLabel('Mobile number').fill('12345');
  await expect(customer.getByText('A mobile number has 10 digits.')).toBeVisible();
  await expect(customer.getByRole('button', { name: 'Place order' })).toBeDisabled();
  await customer.getByLabel('Mobile number').fill('98400 12345');
  await customer.getByLabel('Note for the outlet').fill('Less sugar');
  await expect(customer.getByText('You pay ₹100 at the counter')).toBeVisible();
  await shot(customer, 'foodcourt-4-checkout');
  await customer.getByRole('button', { name: 'Place order' }).click();

  await expect(customer.getByText('Your token')).toBeVisible();
  const token = (await customer.locator('.cx-token strong').textContent()) ?? '';
  expect(token).toMatch(/^[A-Z]{1,2}-\d+$/);
  await expect(customer.getByText('Order received')).toBeVisible();
  await expect(customer.getByText('Pay at the counter')).toBeVisible();
  await shot(customer, 'foodcourt-5-token');

  // the token survives a reload: the customer can close the page and come back
  await customer.reload();
  await expect(customer.locator('.cx-token strong')).toHaveText(token);

  // ---- the outlet sees it, first on the Tables screen, and marks it ready in the kitchen
  await page.locator('.tabs').getByRole('button', { name: 'Tables', exact: true }).click();
  const online = page.getByRole('region', { name: 'Online orders' });
  await expect(online).toContainText(token, { timeout: 30_000 });
  await expect(online).toContainText('2 × Masala tea');
  await expect(online).toContainText('New');
  await shot(page, 'foodcourt-6-outlet');
  await page.getByRole('button', { name: /^Kitchen/ }).click();
  await page.getByRole('button', { name: 'Masala tea ready' }).click();
  await page.getByRole('button', { name: 'Orange juice ready' }).click();

  // ---- the customer's page moves on by itself
  await expect(customer.getByText('Ready to collect')).toBeVisible({ timeout: 30_000 });
  await shot(customer, 'foodcourt-7-ready');
  await customer.context().close();
});

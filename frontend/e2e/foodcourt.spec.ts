/**
 * A food court, end to end in real browsers against the real API: the super admin makes
 * a court and adds outlets; the outlet owner opens for orders; a customer with no login
 * scans the link, orders and follows the token; the outlet sees it on its Tables screen,
 * marks it ready, and the customer's page says so. Screenshots for review.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const ADMIN = process.env.E2E_ADMIN ?? '9840000099';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const phone = { width: 390, height: 844 };

test('a customer orders from a food court outlet and follows it to ready', async ({ page, browser }) => {
  test.setTimeout(120_000);
  await page.setViewportSize(phone);

  // ---- the super admin makes the court and adds two outlets
  const admin = await (await browser.newContext({ viewport: { width: 900, height: 900 } })).newPage();
  await admin.goto('/admin');
  await expect(admin.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await admin.getByLabel('Mobile number').fill('9999999999');
  await admin.getByLabel('Password').fill('wrong-password');
  await admin.getByRole('button', { name: 'Sign in' }).click();
  await expect(admin.getByText('Phone number or password is wrong.')).toBeVisible();
  await admin.getByLabel('Mobile number').fill(ADMIN);
  await admin.getByLabel('Password').fill(PASSWORD);
  await admin.getByRole('button', { name: 'Sign in' }).click();
  await expect(admin.getByRole('heading', { name: 'Food courts' })).toBeVisible();

  await admin.getByRole('button', { name: '+ New food court' }).click();
  await admin.getByLabel('Name customers will see').fill('E2E Food Court');
  await admin.getByRole('button', { name: 'Create food court' }).click();
  const court = admin.getByRole('region', { name: 'E2E Food Court' });
  await expect(court).toBeVisible();
  const link = (await court.locator('.admin-link').textContent()) ?? '';
  expect(link).toMatch(/\/order\/e2e-food-court-[0-9a-f]{4}$/);

  // a shop that already exists, attached by its owner's number
  await court.getByRole('button', { name: '+ Add outlet' }).click();
  const sheet = admin.getByRole('dialog', { name: 'Add an outlet' });
  await sheet.getByLabel("Owner's mobile number").last().fill(OWNER);
  await sheet.getByRole('button', { name: 'Attach' }).click();
  await expect(court.getByRole('list', { name: 'Outlets of E2E Food Court' })).toContainText(OWNER);

  // and a brand-new outlet, with its owner's login and a sample menu
  await court.getByRole('button', { name: '+ Add outlet' }).click();
  await sheet.getByLabel('Outlet name').fill('E2E Anna Biryani');
  await sheet.getByLabel("Owner's name").fill('Anna');
  await sheet.getByLabel("Owner's mobile number").first().fill('98411 55555');
  await sheet.getByLabel('Add a sample menu').check();
  await sheet.getByRole('button', { name: 'Create outlet and add it' }).click();
  const outlets = court.getByRole('list', { name: 'Outlets of E2E Food Court' });
  await expect(outlets).toContainText('E2E Anna Biryani');
  await expect(outlets).toContainText('9841155555');
  await expect(outlets.getByText('Closed')).toHaveCount(2); // nobody takes orders until its owner says so
  await shot(admin, 'foodcourt-1-admin');

  // ---- the outlet owner (a different login) opens for orders
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E food court counter');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await page.locator('.subnav').getByRole('button', { name: 'Food court', exact: true }).click();
  await expect(page.getByText('E2E Food Court').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create food court' })).toHaveCount(0); // not the owner's to make
  const taking = page.getByRole('switch', { name: 'Taking online orders' });
  await expect(taking).toHaveAttribute('aria-checked', 'false'); // off until the outlet says so
  await taking.click();
  await expect(taking).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByLabel('QR code for the food court')).toBeVisible();
  await expect(page.getByRole('list').filter({ hasText: 'E2E Anna Biryani' })).toBeVisible();
  await shot(page, 'foodcourt-2-owner');

  // ---- a customer, with no login and no staff app, scans the QR
  const customer = await (await browser.newContext({ viewport: phone })).newPage();
  await customer.goto(link);
  await expect(customer.getByRole('heading', { name: 'E2E Food Court' })).toBeVisible();
  await expect(customer.getByLabel('Log in')).toHaveCount(0);
  await shot(customer, 'foodcourt-3-outlets');
  await expect(customer.getByRole('button', { name: /Closed/ })).toHaveCount(1); // Anna has not opened
  await customer.getByRole('button', { name: /Open/ }).first().click();
  await customer.getByLabel('Add Masala tea').click();
  await customer.getByLabel('Add one more Masala tea').click();
  await customer.getByLabel('Add Orange juice').click();
  await expect(customer.getByText('3 items · ₹100')).toBeVisible(); // 2 × ₹20 + ₹60
  await shot(customer, 'foodcourt-4-menu');
  await customer.getByRole('button', { name: 'View order' }).click();

  await customer.getByLabel('Your name').fill('Ravi');
  await customer.getByLabel('Mobile number').fill('12345');
  await expect(customer.getByText('A mobile number has 10 digits.')).toBeVisible();
  await expect(customer.getByRole('button', { name: 'Place order' })).toBeDisabled();
  await customer.getByLabel('Mobile number').fill('98400 12345');
  await customer.getByLabel('Note for the outlet').fill('Less sugar');
  await expect(customer.getByText('You pay ₹100 at the counter')).toBeVisible();
  await shot(customer, 'foodcourt-5-checkout');
  await customer.getByRole('button', { name: 'Place order' }).click();

  await expect(customer.getByText('Your token')).toBeVisible();
  const token = (await customer.locator('.cx-token strong').textContent()) ?? '';
  expect(token).toMatch(/^[A-Z]{1,2}-\d+$/);
  await expect(customer.getByText('Order received')).toBeVisible();
  await expect(customer.getByText('Pay at the counter')).toBeVisible();
  await shot(customer, 'foodcourt-6-token');

  // the token survives a reload: the customer can close the page and come back
  await customer.reload();
  await expect(customer.locator('.cx-token strong')).toHaveText(token);

  // ---- the outlet sees it, first on the Tables screen, and marks it ready in the kitchen
  await page.locator('.tabs').getByRole('button', { name: 'Tables', exact: true }).click();
  const online = page.getByRole('region', { name: 'Online orders' });
  await expect(online).toContainText(token, { timeout: 30_000 });
  await expect(online).toContainText('2 × Masala tea');
  await expect(online).toContainText('New');
  await shot(page, 'foodcourt-7-outlet');
  await page.getByRole('button', { name: /^Kitchen/ }).click();
  await page.getByRole('button', { name: 'Masala tea ready' }).click();
  await page.getByRole('button', { name: 'Orange juice ready' }).click();

  // ---- the customer's page moves on by itself
  await expect(customer.getByText('Ready to collect')).toBeVisible({ timeout: 30_000 });
  await shot(customer, 'foodcourt-8-ready');
  await customer.context().close();
  await admin.context().close();
});

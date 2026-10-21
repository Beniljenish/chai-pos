/**
 * A food court, end to end in real browsers against the real API: the super admin makes
 * a court and adds outlets; the outlet owner opens for orders; a customer signs up, picks
 * the food court, puts dishes from two outlets in one cart and gets a token per outlet;
 * the outlet sees its order, marks it ready, and the customer's page says so; the customer
 * sees both in My orders, and a forgotten password is reset by the admin. Screenshots for review.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const ADMIN = process.env.E2E_ADMIN ?? '9840000099';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const phone = { width: 390, height: 844 };

test('a customer signs up, orders from two outlets in one cart and follows the tokens', async ({ page, browser }) => {
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
  await admin.getByLabel('Where it is').fill('E2E Street, Chennai');
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
  let outlets = court.getByRole('list', { name: 'Outlets of E2E Food Court' });
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

  // the owner opened theirs in another browser; the admin's page shows it after a reload, and
  // can open Anna's (an outlet that has not opened cannot be ordered from)
  await admin.reload();
  await expect(admin.getByRole('heading', { name: 'Food courts' })).toBeVisible();
  outlets = admin.getByRole('region', { name: 'E2E Food Court' }).getByRole('list', { name: 'Outlets of E2E Food Court' });
  await expect(outlets.getByText('Taking orders')).toHaveCount(1);
  const anna = outlets.getByRole('listitem').filter({ hasText: 'E2E Anna Biryani' });
  await anna.getByRole('button', { name: 'Open' }).click();
  await expect(outlets.getByText('Taking orders')).toHaveCount(2);

  // ---- a customer opens /order: no staff app, an account of their own
  const customer = await (await browser.newContext({ viewport: phone })).newPage();
  await customer.goto('/order');
  await expect(customer.getByRole('heading', { name: 'Order from your food court' })).toBeVisible();
  await shot(customer, 'foodcourt-3-customer-signup');
  await customer.getByLabel('Your name').fill('Ravi');
  await customer.getByLabel('Mobile number').fill('12345');
  await expect(customer.getByText('A mobile number has 10 digits.')).toBeVisible();
  await expect(customer.getByRole('button', { name: 'Create account and continue' })).toBeDisabled();
  await customer.getByLabel('Mobile number').fill('98400 12345');
  await customer.getByLabel('Choose a password').fill('short');
  await customer.getByRole('button', { name: 'Create account and continue' }).click();
  await expect(customer.getByRole('alert')).toContainText('at least 8 characters');
  await customer.getByLabel('Choose a password').fill('ravi-secret-77');
  await customer.getByRole('button', { name: 'Create account and continue' }).click();

  // ---- pick the food court by searching its name or place
  await expect(customer.getByRole('heading', { name: 'Where are you eating?' })).toBeVisible();
  await customer.getByLabel('Search food court or place').fill('nowhere');
  await expect(customer.getByText('No food court matches')).toBeVisible();
  await customer.getByLabel('Search food court or place').fill('e2e street');
  await expect(customer.getByText('2 of 2 open')).toBeVisible();
  await shot(customer, 'foodcourt-4-pick-court');
  await customer.getByRole('button', { name: /E2E Food Court/ }).click();

  // ---- one cart across two outlets
  await expect(customer.getByRole('heading', { name: 'E2E Food Court' })).toBeVisible();
  const tabs = customer.getByRole('tablist', { name: 'Outlets' });
  await expect(tabs.getByRole('tab')).toHaveCount(2);
  await tabs.getByRole('tab').filter({ hasNotText: 'E2E Anna Biryani' }).click();
  await customer.getByLabel('Add Masala tea').click();
  await customer.getByLabel('Add one more Masala tea').click();
  await customer.getByLabel('Add Orange juice').click();
  await expect(customer.getByText('3 items · 1 outlet · ₹100')).toBeVisible(); // 2 × ₹20 + ₹60
  await tabs.getByRole('tab', { name: /E2E Anna Biryani/ }).click();
  await customer.getByLabel('Add Masala tea').click();
  await expect(tabs.getByLabel('1 in cart')).toBeVisible();
  await expect(customer.getByText('4 items · 2 outlets · ₹120')).toBeVisible();
  await shot(customer, 'foodcourt-5-menu');
  await customer.getByRole('button', { name: 'View cart' }).click();

  await expect(customer.getByRole('region', { name: 'E2E Anna Biryani' })).toContainText('1 × Masala tea');
  await expect(customer.getByText('Ordering as')).toContainText('Ravi');
  await expect(customer.getByText('You pay ₹120 at the counters')).toBeVisible();
  await shot(customer, 'foodcourt-6-cart');
  await customer.getByRole('button', { name: 'Place 2 orders' }).click();

  // ---- a token per outlet
  await expect(customer.getByRole('heading', { name: '2 tokens' })).toBeVisible();
  const tokens = customer.locator('.cx-token strong');
  await expect(tokens).toHaveCount(2);
  const token = (await tokens.first().textContent()) ?? '';
  expect(token).toMatch(/^[A-Z]{1,2}-\d+$/);
  await expect(customer.getByText('Order received')).toHaveCount(2);
  await shot(customer, 'foodcourt-7-tokens');

  // ---- the owner's outlet sees its order first on the Tables screen, and marks it ready
  await page.locator('.tabs').getByRole('button', { name: 'Tables', exact: true }).click();
  const online = page.getByRole('region', { name: 'Online orders' });
  await expect(online).toContainText(token, { timeout: 30_000 });
  await expect(online).toContainText('2 × Masala tea');
  await expect(online).toContainText('Ravi'); // the name and number come from the account
  await shot(page, 'foodcourt-8-outlet');
  await page.getByRole('button', { name: /^Kitchen/ }).click();
  await page.getByRole('button', { name: 'Masala tea ready' }).click();
  await page.getByRole('button', { name: 'Orange juice ready' }).click();

  // ---- the customer's token card moves on by itself, and My orders lists both
  await expect(customer.getByText('Ready to collect')).toBeVisible({ timeout: 30_000 });
  await customer.getByRole('button', { name: 'My orders' }).click();
  await expect(customer.getByRole('list', { name: 'Orders' }).getByRole('listitem')).toHaveCount(2);
  await shot(customer, 'foodcourt-9-my-orders');

  // the login survives a reload
  await customer.goto('/order');
  await expect(customer.getByRole('heading', { name: 'Where are you eating?' })).toBeVisible();

  // ---- log out, a wrong password is refused, the right one works
  await customer.getByRole('button', { name: 'My orders' }).click();
  await customer.getByRole('button', { name: 'Log out' }).click();
  await customer.getByRole('tab', { name: 'Log in' }).click();
  await customer.getByLabel('Mobile number').fill('9840012345');
  await customer.getByLabel('Password').fill('not-my-password');
  await customer.getByRole('button', { name: 'Log in', exact: true }).last().click();
  await expect(customer.getByRole('alert')).toContainText('Phone number or password is wrong.');
  await customer.getByLabel('Password').fill('ravi-secret-77');
  await customer.getByRole('button', { name: 'Log in', exact: true }).last().click();
  await expect(customer.getByRole('heading', { name: 'Where are you eating?' })).toBeVisible();

  // ---- forgot it: the admin resets it, and the customer must choose a new one
  await admin.getByLabel("Customer's mobile number").fill('98400 12345');
  await admin.getByRole('button', { name: 'Reset password' }).click();
  const temp = ((await admin.locator('.admin-temp').textContent()) ?? '').trim();
  expect(temp).toHaveLength(8);
  await customer.reload(); // the old session is over
  await expect(customer.getByRole('tab', { name: 'Log in' })).toBeVisible();
  await customer.getByRole('tab', { name: 'Log in' }).click();
  await customer.getByLabel('Mobile number').fill('9840012345');
  await customer.getByLabel('Password').fill('ravi-secret-77');
  await customer.getByRole('button', { name: 'Log in', exact: true }).last().click();
  await expect(customer.getByRole('alert')).toContainText('Phone number or password is wrong.');
  await customer.getByLabel('Password').fill(temp);
  await customer.getByRole('button', { name: 'Log in', exact: true }).last().click();
  await expect(customer.getByRole('heading', { name: 'Choose a new password' })).toBeVisible();
  await customer.getByLabel('Temporary password').fill(temp);
  await customer.getByLabel('New password').fill('ravi-new-secret-88');
  await customer.getByRole('button', { name: 'Save and continue' }).click();
  await expect(customer.getByRole('heading', { name: 'Where are you eating?' })).toBeVisible();

  await customer.context().close();
  await admin.context().close();
});

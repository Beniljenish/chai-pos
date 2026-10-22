/**
 * Offers and linked outlets (README, "9.19"): the owner makes a code, a customer types it in the
 * cart and sees what it saves, the order shows the offer at the till, and the till bills it with
 * the same discount; then the outlets overview. Runs after foodcourt.spec (needs its court) and
 * starts with zz so it runs after the specs whose menus and orders it must not disturb.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection, submitSignup } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const phone = { width: 390, height: 844 };

test('an offer: made by the owner, applied by a customer, billed at the till', async ({ page, browser }) => {
  test.setTimeout(150_000);
  await page.setViewportSize(phone);
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E offers phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await expect(page.locator('.tile').first()).toBeVisible();

  // ---- the owner makes a 10% offer
  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await openSection(page, 'Offers');
  await page.getByRole('button', { name: '+ New offer' }).click();
  await page.getByLabel('Code', { exact: true }).fill('e2e10');
  await page.getByLabel('Percent off (1 to 100)').fill('10');
  await page.getByRole('button', { name: 'Make the offer' }).click();
  const list = page.getByRole('list', { name: 'Offers' });
  await expect(list).toContainText('E2E10');
  await expect(list).toContainText('10% off');
  await expect(list).toContainText('Working');
  await shot(page, 'offers-1-owner');

  // ---- the food court's link, from the display board section
  await openSection(page, 'Food court');
  const boardUrl = (await page.locator('code', { hasText: '/board/' }).textContent()) ?? '';
  const slug = boardUrl.split('/board/')[1];
  expect(slug).toBeTruthy();

  // ---- a customer applies it in the cart
  const customer = await (await browser.newContext({ viewport: phone })).newPage();
  await customer.goto(`/order/${slug}`);
  await customer.getByLabel('Your name').fill('Offer Ravi');
  await customer.getByLabel('Mobile number').fill('98400 33333');
  await customer.getByLabel('Choose a password').fill('offer-secret-77');
  await submitSignup(customer);
  await expect(customer.getByRole('heading', { name: 'E2E Food Court' })).toBeVisible();
  const tabs = customer.getByRole('tablist', { name: 'Outlets' });
  await tabs.getByRole('tab').filter({ hasNotText: 'E2E Anna Biryani' }).click();
  // Masala tea has options, so adding it opens a sheet: take it as it is (a ₹20 tea: 10% is ₹2)
  await customer.getByLabel('Add Masala tea').click();
  await customer.getByRole('dialog', { name: 'Masala tea' }).getByRole('button', { name: /^Add to cart/ }).click();
  await customer.getByRole('button', { name: 'View cart' }).click();
  await customer.getByLabel('Offer code (optional)').fill('nonsense');
  await customer.getByRole('button', { name: 'Apply' }).click();
  await expect(customer.getByRole('alert').filter({ hasText: 'not valid' })).toBeVisible();
  await customer.getByLabel('Offer code (optional)').fill('e2e10');
  await customer.getByRole('button', { name: 'Apply' }).click();
  await expect(customer.getByText(/Code E2E10 applied: you save ₹2/)).toBeVisible();
  await shot(customer, 'offers-2-cart');
  const counter = customer.getByLabel(/Pay at the counter/);
  if (await counter.count()) await counter.check();
  await customer.getByRole('button', { name: /^Place order/ }).click();
  await expect(customer.locator('.cx-token strong').first()).toBeVisible();

  // ---- the till shows the offer on that order
  await page.locator('.tabs').getByRole('button', { name: 'Tables', exact: true }).click();
  const online = page.getByRole('region', { name: 'Online orders' });
  await expect(online).toContainText('Offer E2E10', { timeout: 30_000 });
  await shot(page, 'offers-3-till');
});

test('the outlets overview shows this outlet', async ({ page }) => {
  await page.setViewportSize(phone);
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E outlets phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await expect(page.locator('.tile').first()).toBeVisible();
  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await openSection(page, 'Outlets');
  await expect(page.getByRole('heading', { name: 'My outlets' })).toBeVisible();
  const cards = page.getByRole('list', { name: 'My outlets' });
  await expect(cards).toContainText('this one');
  await expect(cards).toContainText('Sales today');
  await page.getByRole('button', { name: '+ Link an outlet' }).click();
  await page.getByLabel('Its owner’s mobile number').fill('9000000001'); // this same outlet: refused
  await page.getByLabel('Its owner’s password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Link this outlet' }).click();
  await expect(page.getByRole('alert')).toContainText('same outlet');
  await shot(page, 'outlets-1');
});

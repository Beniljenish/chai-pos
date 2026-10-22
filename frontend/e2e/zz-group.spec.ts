/**
 * Order together (README, "9.21"): a host starts a group, a friend joins from the link and adds a
 * dish, the host sees it, brings everyone's dishes into the cart. Needs the court made by
 * foodcourt.spec, hence the zz.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection, submitSignup } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const phone = { width: 390, height: 844 };

async function signUp(page: Page, name: string, number: string, slug: string) {
  await page.goto(`/order/${slug}`);
  await page.getByLabel('Your name').fill(name);
  await page.getByLabel('Mobile number').fill(number);
  await page.getByLabel('Choose a password').fill('group-secret-77');
  await submitSignup(page);
}

test('friends order together and the host pays for all', async ({ page, browser }) => {
  test.setTimeout(150_000);
  // the court's slug, from the owner's display-board link
  await page.setViewportSize(phone);
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E group phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await expect(page.locator('.tile').first()).toBeVisible();
  await page.locator('.tabs').getByRole('button', { name: 'Manage', exact: true }).click();
  await openSection(page, 'Food court');
  const boardUrl = (await page.locator('code', { hasText: '/board/' }).textContent()) ?? '';
  const slug = boardUrl.split('/board/')[1];

  // ---- the host
  const host = await (await browser.newContext({ viewport: phone })).newPage();
  await signUp(host, 'Host Priya', '98400 55551', slug);
  await expect(host.getByRole('heading', { name: 'E2E Food Court' })).toBeVisible();
  await host.getByRole('button', { name: /Order together/ }).click();
  const panel = host.getByRole('region', { name: 'Order together' });
  await expect(panel).toContainText('1 person');
  const token = await host.evaluate((s) => localStorage.getItem(`taptallow-group:${s}`), slug);
  expect(token).toBeTruthy();

  // ---- a friend opens the link and adds a dish
  const friend = await (await browser.newContext({ viewport: phone })).newPage();
  await friend.goto(`/order/${slug}?group=${token}`);
  await friend.getByLabel('Your name').fill('Friend Ravi');
  await friend.getByLabel('Mobile number').fill('98400 55552');
  await friend.getByLabel('Choose a password').fill('group-secret-77');
  await submitSignup(friend);
  await expect(friend.getByRole('region', { name: 'Order together' })).toContainText('2 people');
  const tabs = friend.getByRole('tablist', { name: 'Outlets' });
  await tabs.getByRole('tab').filter({ hasNotText: 'E2E Anna Biryani' }).click();
  await friend.getByLabel('Add Orange juice').click();
  await friend.getByRole('dialog', { name: 'Orange juice' }).getByRole('button', { name: /^Add to cart/ }).click(); // it has sizes
  await shot(friend, 'group-1-friend');

  // ---- the host sees it (the group is looked at every few seconds) and takes everyone's dishes
  await expect(panel).toContainText('Friend Ravi', { timeout: 20_000 });
  await expect(panel).toContainText('1 × Orange juice', { timeout: 20_000 });
  await shot(host, 'group-2-host');
  await panel.getByRole('button', { name: 'Add everyone’s dishes and pay' }).click();
  await expect(host.getByRole('heading', { name: 'Your cart' })).toBeVisible();
  await expect(host.getByText('1 × Orange juice')).toBeVisible();
  await shot(host, 'group-3-cart');

  // ---- the friend is told the host has gone to pay
  await expect(friend.getByText('The host has gone to pay.')).toBeVisible({ timeout: 20_000 });
});

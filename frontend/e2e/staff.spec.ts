/**
 * Staff accounts on a phone, end to end: the owner adds a cashier, who must set
 * their own password at first login; their sale shows under their name; five
 * wrong passwords lock them out until the owner resets it.
 */
import { expect, test, type Page } from '@playwright/test';
import { saveAndPrint } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const RAVI = '9876500001';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const sheet = (page: Page) => page.getByRole('dialog');
const tab = (page: Page, name: string) => page.locator('.tabs').getByRole('button', { name, exact: true });
const sub = (page: Page, name: string) => page.locator('.subnav').getByRole('button', { name, exact: true });

async function logIn(page: Page, phone: string, password: string) {
  await page.getByLabel('Mobile number').fill(phone);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Log in' }).click();
}

async function logOut(page: Page) {
  await page.locator('.topbar').getByRole('button', { name: 'Log out' }).click();
  await expect(page.getByRole('button', { name: 'Log in' })).toBeVisible();
}

test('owner adds a cashier who sets their own password; lockout and reset', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await logIn(page, OWNER, PASSWORD);
  await page.getByLabel('Tablet name').fill('E2E staff phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  // ---- Owner adds Ravi; the first password is shown once ----
  await tab(page, 'Manage').click();
  await sub(page, 'Staff').click();
  await page.getByRole('button', { name: '+ Add staff' }).click();
  await sheet(page).getByLabel('Name').fill('Ravi');
  await sheet(page).getByLabel('Mobile number (they log in with it)').fill(RAVI);
  await sheet(page).getByRole('button', { name: 'Add cashier' }).click();
  const shown = sheet(page).locator('.first-password .big');
  await expect(shown).toHaveText(/^[a-z]+\d{4}$/);
  const first = (await shown.textContent()) ?? '';
  await shot(page, '40-staff-added');
  await sheet(page).getByRole('button', { name: 'Done' }).click();
  await expect(page.locator('.staff-list li', { hasText: 'Ravi' })).toContainText(
    'Has not set their own password yet',
  );

  // ---- Ravi's first login: must choose his own password ----
  await logOut(page);
  await logIn(page, RAVI, first);
  await expect(page.getByRole('heading', { name: 'Hello Ravi' })).toBeVisible();
  await page.getByLabel('Password the owner gave you').fill(first);
  await page.getByLabel('New password', { exact: true }).fill('12345678');
  await page.getByLabel('New password again').fill('12345678');
  await page.getByRole('button', { name: 'Save my password' }).click();
  await expect(page.getByRole('alert')).toContainText('too easy');
  await page.getByLabel('New password', { exact: true }).fill('masala-tea-77');
  await page.getByLabel('New password again').fill('masala-tea-77');
  await shot(page, '41-set-own-password');
  await page.getByRole('button', { name: 'Save my password' }).click();

  // ---- Straight on to billing, as Ravi ----
  await expect(page.locator('.topbar')).toContainText('Ravi');
  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  await saveAndPrint(page);
  await sheet(page).getByRole('button', { name: 'New bill', exact: true }).click();
  await expect(page.locator('.sync-badge')).toHaveAttribute('aria-label', 'All bills sent', { timeout: 15_000 });
  // Phone top bar regression guard: the name link must not push the tabs onto two rows.
  const tabsBox = await page.locator('.tabs').boundingBox();
  const badgeBox = await page.locator('.sync-badge').boundingBox();
  expect(Math.abs((tabsBox?.y ?? 0) - (badgeBox?.y ?? 999))).toBeLessThan(4);
  // His own password can be changed from his name in the top bar.
  await page.getByRole('button', { name: 'Ravi: change my password' }).click();
  await expect(sheet(page).getByLabel('Current password')).toBeVisible();
  await sheet(page).getByRole('button', { name: 'Close' }).click();
  await logOut(page);

  // ---- Five wrong passwords lock him out ----
  for (let i = 0; i < 5; i++) {
    await logIn(page, RAVI, 'not-my-password');
    await expect(page.getByRole('alert')).toContainText('wrong');
  }
  await logIn(page, RAVI, 'masala-tea-77');
  await expect(page.getByRole('alert')).toContainText('Too many wrong passwords');

  // ---- Owner: Ravi's sale is under his name; unlock with a reset ----
  await logIn(page, OWNER, PASSWORD);
  await tab(page, 'Manage').click();
  await expect(page.locator('.mode-split li', { hasText: 'Ravi' })).toContainText('₹');
  await sub(page, 'Staff').click();
  const ravi = page.locator('.staff-list li', { hasText: 'Ravi' });
  await expect(ravi).toContainText('Locked');
  await ravi.click();
  await sheet(page).getByRole('button', { name: 'Unlock and reset password' }).click();
  await expect(sheet(page).locator('.first-password .big')).toHaveText(/^[a-z]+\d{4}$/);
  const reset = (await sheet(page).locator('.first-password .big').textContent()) ?? '';
  await shot(page, '42-staff-reset');
  await sheet(page).getByRole('button', { name: 'Close' }).click();
  await shot(page, '43-staff-list');
  await logOut(page);

  await logIn(page, RAVI, reset);
  await expect(page.getByRole('heading', { name: 'Hello Ravi' })).toBeVisible();
});

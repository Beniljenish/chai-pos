/**
 * Online payment through Razorpay, on the till. CI's backend has no Razorpay
 * keys (and must never call Razorpay), so the three payment calls are answered
 * in the browser; the server side (signatures, webhook, report) is covered by
 * backend/tests/test_payments.py. What this checks is the till: the bill is
 * saved first, sent, the order asked for, the payment page opened, and the
 * receipt printed once the server says paid.
 */
import { expect, test, type Page } from '@playwright/test';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });

test('a UPI bill collected through Razorpay', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });

  // The server "has keys": the catalogue says online payments are on.
  await page.route('**/api/v1/catalogue', async (route) => {
    const res = await route.fetch();
    if (res.status() !== 200) return route.fulfill({ response: res });
    const body = await res.json();
    body.shop.online_payments = true;
    await route.fulfill({ response: res, json: body, headers: { ...res.headers(), etag: '' } });
  });
  const asked: { bill_id: string; method: string }[] = [];
  await page.route('**/api/v1/payments/razorpay/order', async (route) => {
    const body = route.request().postDataJSON();
    asked.push(body);
    await route.fulfill({
      json: { razorpay_order_id: 'order_E2E1', amount_paise: 2000, method: body.method, status: 'created' },
    });
  });
  let paid = false;
  await page.route('**/api/v1/payments/razorpay/status*', (route) =>
    route.fulfill({ json: paid ? { status: 'paid', paid_paise: 2000, error: '' } : { status: 'created', paid_paise: null, error: '' } }),
  );

  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E online pay phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();

  await page.locator('.tile', { hasText: 'Masala tea' }).click();
  await page.locator('.till-handle').click();
  // Cash: no Razorpay option.
  await expect(page.getByLabel(/Collect through Razorpay/)).toHaveCount(0);
  await page.getByRole('radio', { name: 'UPI' }).click();
  await page.getByLabel(/Collect through Razorpay/).check();
  await page.getByRole('button', { name: 'Save and collect' }).click();
  const start = page.getByRole('dialog', { name: 'Start shift' });
  if (await start.isVisible()) {
    await start.getByLabel('Cash in the drawer now (₹)').fill('500');
    await start.getByRole('button', { name: /^Start shift/ }).click();
  }

  const collect = page.getByRole('dialog', { name: 'Collect ₹20 online' });
  await expect(collect.getByRole('button', { name: 'Open payment page' })).toBeVisible({ timeout: 20_000 });
  expect(asked).toHaveLength(1);
  expect(asked[0].method).toBe('upi');
  await shot(page, '75-collect-online');

  const popup = page.waitForEvent('popup');
  await collect.getByRole('button', { name: 'Open payment page' }).click();
  expect((await popup).url()).toContain('/payments/razorpay/checkout?order_id=order_E2E1');

  paid = true; // the customer paid in the other tab
  const done = page.getByRole('dialog', { name: 'Paid' });
  await expect(done).toContainText('Payment received: ₹20');
  await done.getByRole('button', { name: 'Print receipt' }).click();
  await expect(page.getByRole('dialog', { name: /^Bill / })).toContainText('UPI');
});

/**
 * Tamil and the AI helpers, end to end (README, "9.16"). Runs against a backend started with
 * FAKE_AI=true, where simple rules stand in for the model (the real model cannot run in CI):
 * the owner switches the app to Tamil, watches UPI and changes, buys by typing a note, asks the
 * shop a question and writes a dish's Tamil name; then a customer picks Tamil on the log-in page and
 * sees it through to the dish. File name starts with zz so it runs after the specs whose stock numbers
 * it must not disturb.
 */
import { expect, test, type Page } from '@playwright/test';
import { openSection, submitSignup } from './helpers';

const OWNER = process.env.E2E_OWNER ?? '9000000001';
const PASSWORD = process.env.E2E_PASSWORD ?? 'devpass123';
const shot = (page: Page, name: string) => page.screenshot({ path: `e2e-screenshots/${name}.png`, fullPage: true });
const phone = { width: 390, height: 844 };

test('owner: Tamil switch, Watch, Buy by note, Ask, a dish in Tamil, a bill history', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize(phone);
  await page.goto('/');
  await page.getByLabel('Mobile number').fill(OWNER);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.getByLabel('Tablet name').fill('E2E Tamil phone');
  await page.getByRole('button', { name: 'Set up as a new tablet' }).click();
  await expect(page.locator('.tile').first()).toBeVisible();

  // ---- the language switch is in the account sheet, and the bottom tabs follow it
  // (on a phone the name in the top bar is cut off, so the same sheet opens from Today > Account)
  await page.locator('.tabs').getByRole('button', { name: 'Today' }).click();
  await page.getByRole('button', { name: 'Account', exact: true }).click();
  const account = page.getByRole('dialog');
  await account.getByRole('button', { name: 'தமிழ்' }).click();
  await expect(account.getByRole('button', { name: 'தமிழ்' })).toHaveAttribute('aria-pressed', 'true');
  await expect(account.getByText('டோக்கன்களையும் கட்டணங்களையும் சத்தமாகச் சொல்')).toBeVisible();
  await shot(page, 'tamil-1-account');
  await account.getByRole('button', { name: 'மூடு' }).click();
  await expect(page.locator('.tabs')).toContainText('இன்று');
  await expect(page.locator('.tabs')).toContainText('நிர்வாகம்');
  await shot(page, 'tamil-2-till');

  // ---- Manage in Tamil; the new sections are there
  await page.locator('.tabs').getByRole('button', { name: 'நிர்வாகம்' }).click();
  const nav = page.locator('.subnav');
  for (const label of ['கண்காணிப்பு', 'கேள்', 'வாங்கல்']) await expect(nav.getByRole('button', { name: label, exact: true })).toBeVisible();

  // back to English for the rest of the checks
  await page.locator('.tabs').getByRole('button', { name: 'இன்று' }).click();
  await page.getByRole('button', { name: 'கணக்கு', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'English' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click();

  // ---- Watch: UPI match, changes, GST limit
  await page.locator('.tabs').getByRole('button', { name: 'Manage' }).click();
  await openSection(page, 'Watch');
  await expect(page.getByRole('heading', { name: 'Watch' })).toBeVisible();
  await expect(page.getByText('Every UPI bill against the money Razorpay confirmed.')).toBeVisible();
  await page.getByRole('tab', { name: 'Changes' }).click();
  await expect(page.getByLabel('Day')).toBeVisible();
  await page.getByRole('tab', { name: 'GST limit' }).click();
  await expect(page.getByText(/registered for GST|Type your registration limit/)).toBeVisible();
  await shot(page, 'ai-1-watch');

  // ---- Buy: a typed note becomes a draft, the owner checks it, then it is saved as a stock-in
  await openSection(page, 'Buy');
  await expect(page.getByText('Pretend mode')).toBeVisible();
  await page.getByLabel('What did you buy?').fill('2 dozen paper cups 120 rupees');
  await page.getByRole('button', { name: 'Make a draft' }).click();
  const line = page.locator('.buy-line').first();
  await expect(line.getByLabel('Stock item')).toHaveValue(/.+/);
  await expect(line.getByLabel(/^Quantity/)).toHaveValue('24');
  await expect(line.getByLabel('Total price (₹)')).toHaveValue('120');
  await expect(page.getByText('The lines add up to ₹120.')).toBeVisible();
  await shot(page, 'ai-2-buy-draft');
  await page.getByRole('button', { name: 'Save 1 stock-ins' }).click();
  await expect(page.getByText('All 1 saved.')).toBeVisible();

  // ---- Ask: one tap on an example; the answer comes from the shop's own numbers
  await openSection(page, 'Ask');
  await page.getByRole('button', { name: 'How much did I sell today?' }).click();
  await expect(page.locator('.ask-a')).toContainText('Sales');
  await page.locator('.ask-turns summary').click();
  await expect(page.locator('.ask-turns')).toContainText('bills');
  await shot(page, 'ai-3-ask');

  // ---- A dish in Tamil: the AI fills the boxes, the owner saves
  await openSection(page, 'Shop & GST');
  await page.getByRole('button', { name: /Masala tea/ }).first().click();
  const edit = page.getByRole('dialog', { name: 'Masala tea' });
  await edit.getByRole('button', { name: /Write in Tamil for me/ }).click();
  await expect(edit.getByLabel('Title in Tamil')).toHaveValue('மசாலா டீ');
  await expect(edit.getByText('Written. Please read it')).toBeVisible();
  await edit.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Masala tea' })).toHaveCount(0);

  // ---- A bill's history under Sales: who rang it, and that a bill cannot be edited
  await openSection(page, 'Sales');
  const bills = page.locator('.bill-list button');
  await expect(bills.first()).toBeVisible();
  await bills.first().click();
  const sheet = page.getByRole('dialog').last();
  await sheet.getByRole('button', { name: 'Show bill history' }).click();
  await expect(sheet.getByRole('list', { name: 'Bill history' })).toContainText('Bill rung up');
  await expect(sheet.getByText('A bill cannot be edited')).toBeVisible();
  await shot(page, 'ai-4-bill-history');
});

test('a customer chooses Tamil on the log-in page and sees the dish in Tamil', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize(phone);
  await page.goto('/order');
  await expect(page.getByRole('heading', { name: 'Order from your food court' })).toBeVisible();
  await page.getByRole('button', { name: 'தமிழ்' }).click();
  await expect(page.getByRole('heading', { name: 'உங்கள் உணவு அரங்கிலிருந்து ஆர்டர் செய்யுங்கள்' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'கணக்கை உருவாக்கு' })).toBeVisible();
  await shot(page, 'tamil-3-customer-login');

  const stamp = String(Date.now()).slice(-8);
  await page.getByLabel('உங்கள் பெயர்').fill('தமிழ் வாடிக்கையாளர்');
  await page.getByLabel('கைபேசி எண்').fill(`98${stamp}`);
  await page.getByLabel('கடவுச்சொல்லைத் தேர்ந்தெடுக்கவும்').fill('tamil-pass-1234');
  await submitSignup(page, ['குறியீட்டை அனுப்பு', 'கணக்கை உருவாக்கித் தொடரவும்'], 'செய்தியில் வந்த குறியீடு');

  await expect(page.getByRole('heading', { name: 'எங்கே சாப்பிடப் போகிறீர்கள்?' })).toBeVisible();
  await expect(page.getByPlaceholder('உணவு அரங்கு அல்லது இடத்தைத் தேடுங்கள்')).toBeVisible();
  const court = page.getByRole('button', { name: /E2E Food Court/ });
  await expect(court).toBeVisible();
  await shot(page, 'tamil-4-customer-home');
  const entered = await court.isEnabled();
  if (entered) {
    await court.click();
    // the outlet that owns Masala tea wrote its Tamil name
    const outlets = page.getByRole('tablist', { name: 'கடைகள்' });
    await expect(outlets).toBeVisible();
    await outlets.getByRole('tab', { name: /Demo Tea Stall/ }).click(); // the outlet that wrote the Tamil name
    await expect(page.getByText('மசாலா டீ').first()).toBeVisible();
    await shot(page, 'tamil-5-customer-menu');
  }

  // switching back changes the same screen at once, nothing is lost
  await page.getByRole('button', { name: 'English' }).first().click();
  if (entered) await expect(page.getByRole('tablist', { name: 'Outlets' })).toBeVisible();
  else await expect(page.getByRole('heading', { name: 'Where are you eating?' })).toBeVisible();
});

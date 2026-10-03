import { expect, type Page } from '@playwright/test';

/**
 * Tap "Save and print". The first bill on a tablet with no open drawer shift
 * asks for the cash in the drawer first: answer with `float` rupees.
 */
export async function saveAndPrint(page: Page, float = '500') {
  await page.getByRole('button', { name: 'Save and print' }).click();
  await expect(page.getByRole('dialog').first()).toBeVisible();
  const start = page.getByRole('dialog', { name: 'Start shift' });
  if (await start.isVisible()) {
    await start.getByLabel('Cash in the drawer now (₹)').fill(float);
    await start.getByRole('button', { name: /^Start shift/ }).click();
    await expect(start).toHaveCount(0);
  }
}

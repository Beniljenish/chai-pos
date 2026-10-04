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

/** Phone layout guard (the top bar broke twice): the screen tabs sit in one
 * row at the bottom of the screen, and the top bar is a single row with the
 * sync badge in it. */
export async function expectPhoneBars(page: Page) {
  const vh = page.viewportSize()?.height ?? 844;
  const tabs = await page.locator('.tabs').boundingBox();
  expect(tabs).not.toBeNull();
  expect(Math.abs(tabs!.y + tabs!.height - vh)).toBeLessThan(2); // pinned to the bottom
  expect(tabs!.height).toBeLessThan(90); // one row
  const bar = await page.locator('.topbar').boundingBox();
  const badge = await page.locator('.sync-badge').boundingBox();
  expect(bar!.height).toBeLessThan(80); // one row
  expect(badge!.y).toBeLessThan(bar!.y + bar!.height);
}

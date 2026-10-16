import { test, expect } from '@playwright/test';
import { gate, resetState, gotoApp, placeTrade, parseNum } from './helpers';

test.describe('Watchlist management', () => {
  test.skip(!gate('watchlist'), 'enable with E2E_ENABLE=watchlist');
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async ({ request }) => {
    await resetState(request);
  });

  test('add then remove a ticker', async ({ page }) => {
    await gotoApp(page);
    await page.getByTestId('watchlist-add-input').fill('pypl'); // lowercase is uppercased
    await page.getByTestId('watchlist-add-submit').click();
    await expect(page.getByTestId('watchlist-row-PYPL')).toBeVisible();
    // A freshly added ticker gets a price (simulator prices any symbol).
    await expect(page.getByTestId('watchlist-price-PYPL')).toHaveText(/\d/);

    await page.getByTestId('watchlist-remove-PYPL').click();
    await expect(page.getByTestId('watchlist-row-PYPL')).toHaveCount(0);
  });

  test('invalid tickers are rejected inline', async ({ page }) => {
    await gotoApp(page);
    for (const bad of ['TOOLONG', '123', 'AA-PL']) {
      await page.getByTestId('watchlist-add-input').fill(bad);
      await page.getByTestId('watchlist-add-submit').click();
      await expect(page.getByTestId('watchlist-error')).toBeVisible();
      await expect(page.getByTestId(`watchlist-row-${bad.toUpperCase()}`)).toHaveCount(0);
    }
    await expect(page.locator('[data-testid^="watchlist-row-"]')).toHaveCount(10);
  });

  test('a held ticker removed from the watchlist keeps streaming (PLAN §6)', async ({ page }) => {
    await gotoApp(page);
    await placeTrade(page, 'buy', 'NFLX', '1');
    await expect(page.getByTestId('position-row-NFLX')).toBeVisible();

    await page.getByTestId('watchlist-remove-NFLX').click();
    await expect(page.getByTestId('watchlist-row-NFLX')).toHaveCount(0);

    // Still priced: the position's current price keeps changing.
    const cell = page.getByTestId('position-price-NFLX');
    const first = parseNum(await cell.innerText());
    await expect.poll(async () => parseNum(await cell.innerText()), { timeout: 15_000 }).not.toBe(first);
  });

  test('watchlist survives reload', async ({ page }) => {
    await gotoApp(page);
    await page.getByTestId('watchlist-add-input').fill('AMD');
    await page.getByTestId('watchlist-add-submit').click();
    await expect(page.getByTestId('watchlist-row-AMD')).toBeVisible();
    await page.reload();
    await expect(page.getByTestId('watchlist-row-AMD')).toBeVisible();
    await expect(page.getByTestId('watchlist-row-NFLX')).toHaveCount(0);
  });
});

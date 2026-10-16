import { test, expect } from '@playwright/test';
import { gate, resetState, gotoApp, readCash, readTotal, parseNum, DEFAULT_TICKERS } from './helpers';

test.describe('Fresh start', () => {
  test.skip(!gate('fresh'), 'enable with E2E_ENABLE=fresh');

  test.beforeAll(async ({ request }) => {
    await resetState(request);
  });

  test('default watchlist, $10k cash, streaming prices, empty states', async ({ page }) => {
    await gotoApp(page);

    for (const t of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-row-${t}`)).toBeVisible();
      await expect(page.getByTestId(`watchlist-price-${t}`)).toHaveText(/\d/);
    }
    await expect(page.getByTestId('watchlist-panel').locator('[data-testid^="watchlist-row-"]')).toHaveCount(10);

    expect(await readCash(page)).toBeCloseTo(10000, 2);
    expect(await readTotal(page)).toBeCloseTo(10000, 2);

    // Prices are streaming: AAPL's displayed price changes within a few seconds.
    const price = page.getByTestId('watchlist-price-AAPL');
    const first = parseNum(await price.innerText());
    await expect.poll(async () => parseNum(await price.innerText()), { timeout: 10_000 }).not.toBe(first);

    // Daily change % is shown for each row.
    await expect(page.getByTestId('watchlist-change-AAPL')).toHaveText(/%/);

    // Sparkline accumulates from the stream.
    await expect(page.getByTestId('watchlist-sparkline-AAPL')).toBeVisible();

    // Empty states (PLAN §2).
    await expect(page.getByTestId('heatmap-empty')).toHaveText('No positions — buy something or ask the AI');
    await expect(page.getByTestId('positions-table')).toBeVisible();
    await expect(page.locator('[data-testid^="position-row-"]')).toHaveCount(0);

    // Main chart is present and seeded for the first/selected ticker.
    await expect(page.getByTestId('main-chart')).toBeVisible();
  });

  test('clicking a ticker selects it in the main chart', async ({ page }) => {
    await gotoApp(page);
    await page.getByTestId('watchlist-row-TSLA').click();
    await expect(page.getByTestId('main-chart')).toHaveAttribute('data-ticker', 'TSLA');
  });

  test('no console errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
    await gotoApp(page);
    await page.waitForTimeout(2000);
    expect(errors).toEqual([]);
  });
});

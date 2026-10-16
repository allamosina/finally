import { test, expect } from '@playwright/test';
import { gate, resetState, gotoApp, parseNum } from './helpers';

test.describe('SSE resilience (Chromium)', () => {
  test.skip(!gate('sse'), 'enable with E2E_ENABLE=sse');

  test.beforeAll(async ({ request }) => {
    await resetState(request);
  });

  test('offline turns the dot away from green; online restores it and prices resume', async ({ page, context }) => {
    await gotoApp(page);
    const dot = page.getByTestId('connection-status');
    const price = page.getByTestId('watchlist-price-AAPL');

    await context.setOffline(true);
    await expect(dot).not.toHaveAttribute('data-status', 'connected', { timeout: 5_000 });

    await context.setOffline(false);
    await expect(dot).toHaveAttribute('data-status', 'connected', { timeout: 5_000 });

    // Prices resume after reconnect.
    const first = parseNum(await price.innerText());
    await expect.poll(async () => parseNum(await price.innerText()), { timeout: 10_000 }).not.toBe(first);
  });
});

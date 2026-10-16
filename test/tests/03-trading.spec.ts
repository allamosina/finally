import { test, expect } from '@playwright/test';
import { gate, resetState, gotoApp, placeTrade, readCash, parseNum } from './helpers';

test.describe('Buy and sell', () => {
  test.skip(!gate('trading'), 'enable with E2E_ENABLE=trading');
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async ({ request }) => {
    await resetState(request);
  });

  test('buy: cash decreases, position appears, portfolio updates', async ({ page }) => {
    await gotoApp(page);
    const cashBefore = await readCash(page);

    await placeTrade(page, 'buy', 'AAPL', '10');
    await expect(page.getByTestId('position-row-AAPL')).toBeVisible();
    await expect(page.getByTestId('position-qty-AAPL')).toHaveText(/^10(\.0+)?$/);

    const avg = parseNum(await page.getByTestId('position-avg-cost-AAPL').innerText());
    await expect.poll(async () => cashBefore - (await readCash(page))).toBeCloseTo(10 * avg, 0);
    // Cash decreased by roughly qty * price (display is rounded to cents).
    expect(Math.abs(cashBefore - (await readCash(page)) - 10 * avg)).toBeLessThan(0.1);

    // Current price, unrealized P&L and P&L % columns are populated.
    await expect(page.getByTestId('position-price-AAPL')).toHaveText(/\d/);
    await expect(page.getByTestId('position-pnl-AAPL')).toHaveText(/\d/);
    await expect(page.getByTestId('position-pnl-pct-AAPL')).toHaveText(/%/);
  });

  test('fractional quantity is accepted', async ({ page }) => {
    await gotoApp(page);
    await placeTrade(page, 'buy', 'MSFT', '0.5');
    await expect(page.getByTestId('position-qty-MSFT')).toHaveText(/^0\.5(0+)?$/);
  });

  test('lowercase ticker input works', async ({ page }) => {
    await gotoApp(page);
    await placeTrade(page, 'buy', 'googl', '1');
    await expect(page.getByTestId('position-row-GOOGL')).toBeVisible();
  });

  test('buying more than cash allows shows an inline error and changes nothing', async ({ page }) => {
    await gotoApp(page);
    const cash = await readCash(page);
    await placeTrade(page, 'buy', 'AAPL', '1000000');
    await expect(page.getByTestId('trade-error')).toContainText('Insufficient cash');
    expect(await readCash(page)).toBeCloseTo(cash, 2);
  });

  test('invalid quantity and ticker show an inline error', async ({ page }) => {
    await gotoApp(page);
    await placeTrade(page, 'buy', 'AAPL', '0');
    await expect(page.getByTestId('trade-error')).toBeVisible();
    await placeTrade(page, 'buy', 'NOPE1', '1');
    await expect(page.getByTestId('trade-error')).toBeVisible();
  });

  test('sell: cash increases, quantity drops, row stays', async ({ page }) => {
    await gotoApp(page);
    const cashBefore = await readCash(page);
    await placeTrade(page, 'sell', 'AAPL', '4');
    await expect(page.getByTestId('position-qty-AAPL')).toHaveText(/^6(\.0+)?$/);
    expect(await readCash(page)).toBeGreaterThan(cashBefore);
  });

  test('selling more than held shows an inline error', async ({ page }) => {
    await gotoApp(page);
    await placeTrade(page, 'sell', 'AAPL', '100');
    await expect(page.getByTestId('trade-error')).toContainText('Insufficient shares');
    await expect(page.getByTestId('position-qty-AAPL')).toHaveText(/^6(\.0+)?$/);
  });

  test('selling everything removes the row', async ({ page }) => {
    await gotoApp(page);
    await placeTrade(page, 'sell', 'AAPL', '6');
    await expect(page.getByTestId('position-row-AAPL')).toHaveCount(0);
  });

  test('state survives reload', async ({ page }) => {
    await gotoApp(page);
    await page.reload();
    await expect(page.getByTestId('position-row-MSFT')).toBeVisible();
    await expect(page.getByTestId('position-row-AAPL')).toHaveCount(0);
  });
});

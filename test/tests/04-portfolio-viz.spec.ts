import { test, expect } from '@playwright/test';
import { gate, resetState, gotoApp, placeTrade, parseRgb } from './helpers';

test.describe('Portfolio visualisation', () => {
  test.skip(!gate('viz'), 'enable with E2E_ENABLE=viz');
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async ({ request }) => {
    await resetState(request);
  });

  test('empty state before any trade, P&L chart already has a flat line', async ({ page }) => {
    await gotoApp(page);
    await expect(page.getByTestId('heatmap-empty')).toBeVisible();
    await expect(page.getByTestId('pnl-chart')).toBeVisible();
  });

  test('heatmap cells exist per position and are coloured by P&L sign', async ({ page }) => {
    await gotoApp(page);
    await placeTrade(page, 'buy', 'AAPL', '5');
    await expect(page.getByTestId('position-row-AAPL')).toBeVisible();
    await placeTrade(page, 'buy', 'TSLA', '5');
    await expect(page.getByTestId('position-row-TSLA')).toBeVisible();

    await expect(page.getByTestId('heatmap-empty')).toHaveCount(0);
    for (const t of ['AAPL', 'TSLA']) {
      const cell = page.getByTestId(`heatmap-cell-${t}`);
      await expect(cell).toBeVisible();
      // The frontend marks the sign; the fill colour must agree with it.
      // Prices are random, so we assert consistency, not a particular sign.
      await expect.poll(async () => {
        const sign = await cell.getAttribute('data-pnl-sign');
        const fill = await cell.evaluate((el) => {
          const r = el.tagName.toLowerCase() === 'rect' ? el : el.querySelector('rect');
          return r ? getComputedStyle(r).fill : '';
        });
        if (!fill || fill === 'none') return 'no-fill';
        const [r, g, b] = parseRgb(fill);
        if (sign === 'profit') return g > r && g > b ? 'ok' : `profit but fill=${fill}`;
        if (sign === 'loss') return r > g && r > b ? 'ok' : `loss but fill=${fill}`;
        return sign === 'flat' ? 'ok' : `unknown sign ${sign}`;
      }).toBe('ok');
    }
  });

  test('P&L chart has data points that grow after a trade', async ({ page }) => {
    await gotoApp(page);
    const chart = page.getByTestId('pnl-chart');
    await expect(chart).toHaveAttribute('data-point-count', /^[1-9]\d*$/);
    const before = Number(await chart.getAttribute('data-point-count'));
    await placeTrade(page, 'buy', 'NVDA', '1'); // a snapshot is recorded immediately after each trade
    await expect.poll(async () => Number(await chart.getAttribute('data-point-count')), { timeout: 15_000 }).toBeGreaterThan(before);
  });

  test('selling everything returns the heatmap to its empty state', async ({ page }) => {
    await gotoApp(page);
    for (const t of ['AAPL', 'TSLA', 'NVDA']) {
      const qty = t === 'NVDA' ? '1' : '5';
      await placeTrade(page, 'sell', t, qty);
      await expect(page.getByTestId(`position-row-${t}`)).toHaveCount(0);
    }
    await expect(page.getByTestId('heatmap-empty')).toBeVisible();
  });
});

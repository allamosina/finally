import { test, expect } from '@playwright/test';
import { gate, resetState, gotoApp, sendChat, readCash } from './helpers';

// Ordered: the failed sell in step 2 relies on the 5 AAPL bought in step 1.
test.describe('AI chat (LLM_MOCK=true)', () => {
  test.skip(!gate('chat'), 'enable with E2E_ENABLE=chat');
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async ({ request }) => {
    await resetState(request);
  });

  test('buy 5 AAPL gives an executed chip and updates the portfolio; sell 500 AAPL gives a failed chip', async ({ page }) => {
    await gotoApp(page);
    const cashBefore = await readCash(page);

    await sendChat(page, 'buy 5 AAPL');
    const executed = page.getByTestId('chat-chip').filter({ hasText: 'AAPL' }).first();
    await expect(executed).toBeVisible({ timeout: 15_000 });
    await expect(executed).toHaveAttribute('data-status', 'executed');
    await expect(page.getByTestId('chat-message').last()).toContainText('[mock]');

    // The portfolio refetches after the chat response (PLAN §10).
    await expect(page.getByTestId('position-qty-AAPL')).toHaveText(/^5(\.0+)?$/);
    expect(await readCash(page)).toBeLessThan(cashBefore);

    await sendChat(page, 'sell 500 AAPL');
    const failed = page.locator('[data-testid="chat-chip"][data-status="failed"]').first();
    await expect(failed).toBeVisible({ timeout: 15_000 });
    await expect(failed).toContainText('Insufficient shares');
    await expect(page.getByTestId('position-qty-AAPL')).toHaveText(/^5(\.0+)?$/); // unchanged
  });

  test('watchlist change by chat', async ({ page }) => {
    await gotoApp(page);
    await sendChat(page, 'add PYPL');
    await expect(page.locator('[data-testid="chat-chip"][data-status="executed"]').filter({ hasText: 'PYPL' })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('watchlist-row-PYPL')).toBeVisible();
    await sendChat(page, 'remove PYPL');
    await expect(page.getByTestId('watchlist-row-PYPL')).toHaveCount(0);
  });

  test('plain message gets a canned [mock] summary with no chips', async ({ page }) => {
    await gotoApp(page);
    await openChatAndCount(page);
  });

  test('history (with chips) is restored after reload', async ({ page }) => {
    await gotoApp(page);
    await page.reload();
    await page.getByTestId('connection-status').waitFor();
    await expect(page.locator('[data-testid="chat-chip"][data-status="failed"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="chat-chip"][data-status="executed"]').first()).toBeVisible();
  });
});

async function openChatAndCount(page: import('@playwright/test').Page) {
  const chipsBefore = await page.getByTestId('chat-chip').count();
  await sendChat(page, 'how is my portfolio doing?');
  await expect(page.getByTestId('chat-message').last()).toContainText('[mock]', { timeout: 15_000 });
  await expect(page.getByTestId('chat-loading')).toHaveCount(0);
  expect(await page.getByTestId('chat-chip').count()).toBe(chipsBefore);
}


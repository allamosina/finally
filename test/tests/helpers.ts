import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const DEFAULT_TICKERS = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'NFLX'];

/**
 * Specs are skipped until their feature exists (TEAM.md wave 3 unskips them).
 * Enable with E2E_ENABLE=all, or a comma list of group names, e.g. E2E_ENABLE=api,fresh.
 * Unskipping permanently is a one-line change: replace `gate('x')` with `true` in that spec.
 */
export function gate(group: string): boolean {
  const v = process.env.E2E_ENABLE ?? '';
  return v === 'all' || v.split(',').map((s) => s.trim()).includes(group);
}

export async function resetState(request: APIRequestContext): Promise<void> {
  const res = await request.post('/api/reset');
  expect(res.ok(), `POST /api/reset -> ${res.status()}`).toBeTruthy();
}

/** "$10,000.00" / "-$12.30" / "+1.25%" -> number */
export function parseNum(text: string | null): number {
  if (!text) return NaN;
  const cleaned = text.replace(/[^0-9.\-]/g, '');
  return Number(cleaned);
}

export async function gotoApp(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected');
  await expect(page.getByTestId('watchlist-panel')).toBeVisible();
}

export async function readCash(page: Page): Promise<number> {
  return parseNum(await page.getByTestId('header-cash').innerText());
}

export async function readTotal(page: Page): Promise<number> {
  return parseNum(await page.getByTestId('header-total-value').innerText());
}

export async function placeTrade(page: Page, side: 'buy' | 'sell', ticker: string, qty: string): Promise<void> {
  await page.getByTestId('trade-ticker').fill(ticker);
  await page.getByTestId('trade-quantity').fill(qty);
  await page.getByTestId(side === 'buy' ? 'trade-buy' : 'trade-sell').click();
}

/** Open the (collapsible) chat sidebar if it is closed. */
export async function openChat(page: Page): Promise<void> {
  if (!(await page.getByTestId('chat-input').isVisible())) {
    await page.getByTestId('chat-toggle').click();
  }
  await expect(page.getByTestId('chat-input')).toBeVisible();
}

export async function sendChat(page: Page, text: string): Promise<void> {
  await openChat(page);
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
}

/** Parse an "rgb(r, g, b)" / "rgba(...)" string. */
export function parseRgb(css: string): [number, number, number] {
  const m = css.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
  if (!m) throw new Error(`not an rgb colour: ${css}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

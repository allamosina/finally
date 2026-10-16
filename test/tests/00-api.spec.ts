import { test, expect } from '@playwright/test';
import { gate, resetState, DEFAULT_TICKERS } from './helpers';

// API contract checks (PLAN §8). Needs only the backend, not the frontend.
test.describe('API contract', () => {
  test.skip(!gate('api'), 'enable with E2E_ENABLE=api');
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async ({ request }) => {
    await resetState(request);
  });

  test('health reports ok, simulator and mock LLM', async ({ request }) => {
    const res = await request.get('/api/health');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ status: 'ok', market_data: 'simulator', llm: 'mock', db: 'ok' });
  });

  test('portfolio starts at $10,000 with no positions', async ({ request }) => {
    const body = await (await request.get('/api/portfolio')).json();
    expect(body.cash_balance).toBeCloseTo(10000, 6);
    expect(body.total_value).toBeCloseTo(10000, 6);
    expect(body.positions).toEqual([]);
  });

  test('watchlist has the ten defaults with prices', async ({ request }) => {
    const body = await (await request.get('/api/watchlist')).json();
    const list = Array.isArray(body) ? body : body.watchlist ?? body.tickers;
    const tickers = list.map((r: { ticker: string }) => r.ticker).sort();
    expect(tickers).toEqual([...DEFAULT_TICKERS].sort());
  });

  test('bad input is 422, business rules are 400, missing delete is 404', async ({ request }) => {
    expect((await request.post('/api/watchlist', { data: { ticker: '123' } })).status()).toBe(422);
    expect((await request.post('/api/watchlist', { data: { ticker: 'TOOLONG' } })).status()).toBe(422);
    expect((await request.post('/api/portfolio/trade', { data: { ticker: 'AAPL', quantity: 0, side: 'buy' } })).status()).toBe(422);
    expect((await request.post('/api/portfolio/trade', { data: { ticker: 'AAPL', quantity: -1, side: 'buy' } })).status()).toBe(422);
    const big = await request.post('/api/portfolio/trade', { data: { ticker: 'AAPL', quantity: 1e6, side: 'buy' } });
    expect(big.status()).toBe(400);
    expect((await big.json()).detail).toMatch(/^Insufficient cash: need \$[\d,]+\.\d{2}, have \$10,000\.00$/);
    const sell = await request.post('/api/portfolio/trade', { data: { ticker: 'AAPL', quantity: 5, side: 'sell' } });
    expect(sell.status()).toBe(400);
    expect((await sell.json()).detail).toMatch(/^Insufficient shares: have 0, selling 5$/);
    expect((await request.delete('/api/watchlist/ZZZZ')).status()).toBe(404);
  });

  test('trade returns trade + portfolio; lowercase ticker accepted; history grows', async ({ request }) => {
    const res = await request.post('/api/portfolio/trade', { data: { ticker: 'aapl', quantity: 2.5, side: 'buy' } });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.trade.ticker).toBe('AAPL');
    expect(body.portfolio.positions[0]).toMatchObject({ ticker: 'AAPL', quantity: 2.5 });
    const hist = await (await request.get('/api/portfolio/history')).json();
    expect(hist.length).toBeGreaterThanOrEqual(1);
    expect(hist[hist.length - 1].recorded_at).toMatch(/Z$/);
  });

  test('price history and SSE snapshot', async ({ request }) => {
    const h = await (await request.get('/api/prices/AAPL/history')).json();
    expect(Array.isArray(h)).toBe(true);
    expect(h.length).toBeGreaterThan(0);
    expect(h.length).toBeLessThanOrEqual(600);
    expect(h[0]).toHaveProperty('ts');
    expect(h[0]).toHaveProperty('price');
  });

  test('reset restores seed state', async ({ request }) => {
    expect((await request.post('/api/reset')).status()).toBe(200);
    const body = await (await request.get('/api/portfolio')).json();
    expect(body.cash_balance).toBeCloseTo(10000, 6);
    expect(body.positions).toEqual([]);
    const chat = await (await request.get('/api/chat/history')).json();
    expect(chat).toEqual([]);
  });

  test('chat (mock) executes and records failures', async ({ request }) => {
    const ok = await (await request.post('/api/chat', { data: { message: 'buy 1 MSFT' } })).json();
    expect(ok.message).toMatch(/^\[mock\] /);
    expect(ok.actions.trades[0]).toMatchObject({ ticker: 'MSFT', side: 'buy', status: 'executed', error: null });
    const bad = await (await request.post('/api/chat', { data: { message: 'sell 500 MSFT' } })).json();
    expect(bad.actions.trades[0]).toMatchObject({ status: 'failed', price: null });
    expect(bad.actions.trades[0].error).toMatch(/Insufficient shares/);
    await resetState(request);
  });
});

# FinAlly E2E tests

Playwright (Chromium, TypeScript). Specs map to PLAN §12. All specs share one single-user server state, so they run serially and each file calls `POST /api/reset` in `beforeAll`.

## Against a locally running app (no Docker)

```bash
cd test && npm install
BASE_URL=http://localhost:8000 E2E_ENABLE=all npx playwright test   # BASE_URL defaults to this
npx playwright install chromium                                      # once
```

The app needs `LLM_MOCK=true`. `E2E_ENABLE` takes `all` or a comma list of groups: `api, fresh, watchlist, trading, viz, chat, sse`. Without it every spec is skipped. `api` needs only the backend.

## In Docker

```bash
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down -v
```

## Selectors

Only `data-testid`. The contract is in `test-ids.md`.

# FinAlly Build Team

The charter for the agent team that builds FinAlly from [PLAN.md](PLAN.md). Every teammate reads PLAN.md in full, then this file, then the documents named under their role. PLAN.md is the contract; this file only divides the work and fixes the seams between roles.

## 1. Roles and ownership

| Teammate | Owns (write access) | Reads but does not edit |
|---|---|---|
| **db-engineer** | `backend/db/` (schema SQL, seed data), `backend/app/db/` (connection, init, repository functions, trade transaction), `backend/tests/db/` | `backend/app/market/` |
| **backend-engineer** | `backend/app/main.py`, `backend/app/api/` (routes), `backend/app/services/` (portfolio, watchlist, snapshots), `backend/app/sse.py`, `backend/pyproject.toml`, `backend/tests/api/`, `backend/tests/services/`, `backend/app/market/` (bug fixes only) | `backend/app/db/`, `backend/app/llm/` |
| **llm-engineer** | `backend/app/llm/` (client, prompt, output schema, mock, action executor), `backend/tests/llm/` | `backend/app/services/`, `backend/app/db/` |
| **frontend-engineer** | `frontend/` entirely | `backend/app/api/` (to match shapes) |
| **devops-engineer** | `Dockerfile`, `.dockerignore`, `scripts/`, `.env.example`, `db/.gitkeep`, `test/docker-compose.test.yml`, README "Running" section | everything else |
| **integration-tester** | `test/` (Playwright project, specs, config), `test/docker-compose.test.yml` jointly with devops | everything |

Rules:

- Edit only what you own. If you need a change elsewhere, message the owner with the exact change and why. Do not wait silently; keep working on something else.
- Unit tests live beside the code you own and are your responsibility. Nobody ships code without tests for its pure logic (PLAN §12).
- Keep `planning/REVIEW.md` untouched; the Stop hook writes there.
- Commit nothing. The lead commits at milestones.

## 2. Seams between roles

These are the interfaces two roles share. They are fixed here so teammates can work in parallel; change them only by agreement over messages, and update this file when you do.

### 2.1 Database access layer (`backend/app/db/`), owned by db-engineer

```python
# backend/app/db/__init__.py
async def init_db(path: str) -> None          # create file, WAL mode, schema, seed if empty; idempotent
def connect() -> aiosqlite.Connection | sqlite3.Connection   # short-lived per operation, see PLAN §7
```

Repository functions, all taking `user_id: str = "default"`:

```python
# backend/app/db/repo.py
async def get_profile() -> Profile                      # {id, cash_balance, created_at}
async def list_watchlist() -> list[str]
async def add_watchlist(ticker) -> bool                  # False if already present
async def remove_watchlist(ticker) -> bool               # False if absent  -> route returns 404
async def list_positions() -> list[Position]            # {ticker, quantity, avg_cost, updated_at}
async def priced_set() -> set[str]                      # watchlist ∪ positions
async def execute_trade(ticker, side, quantity, price, total_value_after) -> Trade
#   One transaction: validates cash / shares with 1e-6 tolerance, updates cash, upserts or deletes
#   the position (weighted avg_cost on buy, unchanged on sell), appends trades row, appends
#   portfolio_snapshots row. Raises InsufficientCash / InsufficientShares with the PLAN §8 message.
async def record_snapshot(total_value) -> None
async def list_snapshots(limit=500, since=None) -> list[Snapshot]
async def list_chat(limit=50) -> list[ChatMessage]       # oldest first
async def add_chat(role, content, actions: dict | None) -> ChatMessage
async def reset() -> None                                # PLAN §7 Reset
```

Timestamps are ISO-8601 UTC with `Z` (PLAN §7). Money is `REAL`. The caller supplies `price` and the post-trade `total_value`; the repo never reads the price cache.

### 2.2 Portfolio service (`backend/app/services/portfolio.py`), owned by backend-engineer

```python
async def trade(ticker: str, side: str, quantity: float) -> tuple[Trade, PortfolioView]
#   validates ticker (^[A-Z]{1,5}$ after upper) and quantity (> 0, finite, round 4) -> 422 shapes
#   await source.prime({ticker}); 503 "Price unavailable for X" if absent
#   price = cache.get(ticker).price; calls repo.execute_trade; then source.set_tickers(priced_set)
async def view() -> PortfolioView                        # the GET /api/portfolio object, priced from cache
async def watchlist_add(ticker) / watchlist_remove(ticker)   # both call source.set_tickers afterwards
```

This is the **only** trade path. The LLM action executor and the REST route both call `services.portfolio.trade()`, so one validation and one error vocabulary exist.

### 2.3 LLM module (`backend/app/llm/`), owned by llm-engineer

```python
async def chat(message: str) -> ChatResponse             # the PLAN §9 response object
#   builds context from services.portfolio.view() + repo.list_watchlist() + cache prices
#   loads last 20 chat rows, calls the model once (or the mock), executes actions through
#   services.portfolio, persists both messages via repo.add_chat, returns the response
def status() -> Literal["live", "mock", "unconfigured"]  # for /api/health
```

The route in `backend/app/api/chat.py` is a thin wrapper: 503 when `status() == "unconfigured"`, otherwise `await llm.chat(body.message)`.

### 2.4 HTTP API

PLAN §8 is the contract. The frontend-engineer codes against PLAN §8 from day one and does not wait for the backend. The backend-engineer posts a message to the team the moment each route group is live locally so the tester and frontend can switch from mocks to the real thing.

### 2.5 Static serving

Frontend builds to `frontend/out/`. The Dockerfile copies it to `/app/static/`. `main.py` mounts it at `/` with SPA fallback (PLAN §11) and reads the directory from `STATIC_DIR` (default `static`), so local dev can point at `../frontend/out`. `trailingSlash: false` in `next.config`; FastAPI serves `index.html` for `/` and for any unknown non-`/api` path.

## 3. Order of work

Work in parallel wherever the seams allow. Dependencies that block are marked.

**Wave 1 (start immediately, all in parallel)**

- db-engineer: schema, init, seed, repo functions, `execute_trade` transaction, unit tests. Target: done first; everyone depends on it.
- backend-engineer: `pyproject.toml` dependencies (`fastapi`, `uvicorn[standard]`, `aiosqlite` or stdlib sqlite, `python-dotenv`, `litellm`, `pydantic`, `httpx`; dev: `pytest`, `pytest-asyncio`), `main.py` lifespan wiring the market source (MARKET_INTERFACE.md §8), SSE route, history route, health route. Stub the repo calls until db-engineer delivers, then switch.
- llm-engineer: output schema (Pydantic), system prompt, mock-mode parser, response parsing with retry-then-fallback, unit tests. Use `.claude/skills/cerebras/SKILL.md` for the LiteLLM call. Action execution waits on the portfolio service.
- frontend-engineer: Next.js project (`output: 'export'`, Tailwind, Recharts), layout, SSE reducer, watchlist with flashes and sparklines, main chart, trade bar, header. Mock API with static JSON until the backend is up. Pure-function unit tests for P&L math, formatters, SSE reducer.
- devops-engineer: `Dockerfile` (multi-stage per PLAN §11, `--workers 1`), `.dockerignore`, `.env.example` (PLAN §5 plus MARKET_INTERFACE.md §10), `scripts/start_mac.sh`, `scripts/stop_mac.sh`, `scripts/start_windows.ps1`, `scripts/stop_windows.ps1`, `db/.gitkeep`. Build against whatever exists; rebuild as the others land.
- integration-tester: Playwright project in `test/` (TypeScript, Chromium), `test/docker-compose.test.yml` with devops, spec skeletons for every PLAN §12 scenario, a `beforeAll` that calls `POST /api/reset`. Mark specs `test.skip` until the feature exists.

**Wave 2 (blocked on wave 1 pieces)**

- backend-engineer: portfolio and watchlist services and routes (needs repo), snapshot task every 30 s, reset route. Blocked on db-engineer.
- llm-engineer: action executor and `chat()` end to end, history route. Blocked on portfolio service.
- frontend-engineer: positions table, heatmap, P&L chart, chat panel with action chips, connection status dot. Switch from mocks to live API as route groups are announced.
- backend-engineer: run the whole backend locally with `STATIC_DIR=../frontend/out`, confirm the SPA loads.

**Wave 3 (integration)**

- devops-engineer: full image build, `start_mac.sh` end to end, health poll, browser opens.
- integration-tester: unskip specs, run the suite against the compose stack with `LLM_MOCK=true`. For every failure, message the owning teammate with: spec name, steps, expected vs actual, and the relevant log lines. Re-run after the owner reports the fix. Keep a running list in `test/ISSUES.md` (open / fixed).
- Everyone: fix what the tester reports before starting anything new.

Done means: all PLAN §12 unit tests green in `backend/` and `frontend/`, the Playwright suite green in `test/docker-compose.test.yml`, `./scripts/start_mac.sh` from a clean clone opens a working app, README "Running" section accurate.

## 4. Communication

- Announce in one line when a seam is live: "portfolio routes up on :8000", "frontend static export builds", "image builds and health is ok".
- A bug report names the owner, the file, the repro and the expected behaviour. The owner replies when fixed, naming the commit-free change ("fixed in services/portfolio.py, rounding before validation").
- A seam change (section 2) is proposed to the other side first, agreed, then applied in this file and in code.
- If PLAN.md is ambiguous, pick the reading a careful engineer would, note it in your message to the lead, and continue. Do not block on a question.

## 5. Models

| Teammate | Model | Why |
|---|---|---|
| frontend-engineer | opus | Largest surface, visual judgement, many moving parts (SSE reducer, Recharts, flashes, chat chips) |
| backend-engineer | opus | Owns the wiring everyone else depends on: lifespan, SSE, services, static serving |
| llm-engineer | sonnet | Small, well-specified module with a skill file to follow |
| db-engineer | sonnet | Schema and a single transaction, fully spelled out in PLAN §7 |
| devops-engineer | sonnet | Dockerfile and scripts are specified line by line in PLAN §11 |
| integration-tester | sonnet | Playwright specs map one to one onto PLAN §12 scenarios |

The lead runs on the session model and writes no code.

## 6. Role briefs

**db-engineer.** PLAN §7 is yours. Schema exactly as listed, `user_id` on every table, UNIQUE constraints, WAL mode, short-lived connections. The trade transaction is the one piece of business logic you own; test weighted average cost, full-sell deletion, tolerance edges, and the exact error strings. `reset()` restores seed state including the ten default tickers.

**backend-engineer.** PLAN §6, §8, §11 (static serving) and MARKET_INTERFACE.md §8–§9. Wire the existing `backend/app/market/` package; do not rewrite it. SSE: one event per cache change, `retry: 2000`, `: ping` every 15 s, `direction` and `change_pct` per Quote. Health reports `market_data`, `llm`, `db`. Status codes per PLAN §8 conventions. Fix the two open simulator findings in REVIEW.md (`set_tickers` not dropping primed-only tickers; `drop()` not bumping the version) while you are there.

**llm-engineer.** PLAN §9 and `.claude/skills/cerebras/SKILL.md`. Model `openrouter/openai/gpt-oss-120b`, provider order `["cerebras"]`, structured output via `response_format` with a Pydantic model, `reasoning_effort="low"`. One call per message, retry once on bad JSON, raw text fallback. Mock mode is a deterministic parser prefixed `[mock] `; it must go through the real action executor. The system prompt must forbid claiming a trade succeeded. Persist `actions` including failures. Never log the API key.

**frontend-engineer.** PLAN §2 and §10. Load the `frontend-design` skill before laying out the page; the brief is a dark, dense Bloomberg-style terminal using the three brand colours. Recharts only. `EventSource` on `/api/stream/prices`, one reducer per event, client-side recomputation of header total, positions and heatmap between portfolio fetches. Price flash via a CSS class removed after ~500 ms. Empty states per PLAN §2. Use `context7` for current Next.js and Recharts API details rather than guessing.

**devops-engineer.** PLAN §11. Node 20 slim build stage, Python 3.12 slim runtime with `uv sync --frozen`, `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`. Bind mount `./db:/app/db`, `--env-file .env`, container name `finally`. Scripts idempotent, poll `/api/health` until `status: ok`, print the URL, open the browser on macOS. `.env.example` documents every variable.

**integration-tester.** PLAN §12. Playwright in its own container (`mcr.microsoft.com/playwright`), app container built from the repo `Dockerfile`, fresh empty `db/` volume, `LLM_MOCK=true`. Cover every listed scenario including the SSE resilience test with `context.setOffline`. Report, do not fix: your value is an independent eye. When the suite is green, say so and list anything you saw that is not covered by a spec.

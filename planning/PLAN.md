# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

## 2. User Experience

### First Launch

The user runs a single start script. A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- $10,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area, seeded with the last ~5 minutes of price history from the backend and then extended live
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog. Quantity is any finite number > 0, rounded to 4 decimals (fractional shares allowed)
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, P&L % (return vs. average cost)
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet
- **Empty states**: with no positions the heatmap shows "No positions — buy something or ask the AI"; the P&L chart renders a flat line from the first snapshot

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving         │
│                      (Next.js export)            │
│                                                 │
│  SQLite database (bind-mounted ./db)            │
│  Background tasks: market simulator, snapshots  │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/finally.db`, bind-mounted for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: a built-in simulator behind an abstract `MarketDataSource` interface. A real-data client (Massive API) is a **stretch goal** (see §11) and is not part of the core build.

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; no docker-compose for production, no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |
| Simulator only in core | Real market data cannot be tested in CI, needs a paid key to look live, and is flat outside market hours. The interface keeps the door open. |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── db/                   # Schema definitions, seed data, migration logic
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   ├── REVIEW.md             # Change review log (appended by the Stop hook)
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── db/                       # Bind-mount target (SQLite file lives here at runtime)
│   └── .gitkeep              # Directory exists in repo; finally.db is gitignored
├── Dockerfile                # Multi-stage build (Node → Python)
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

There is deliberately **no top-level `docker-compose.yml`**: the start/stop scripts are the single way to run the app. `test/docker-compose.test.yml` exists because the E2E setup genuinely orchestrates two containers.

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/db/`** contains schema SQL definitions and seed logic. The backend lazily initializes the database on first request — creating tables and seeding default data if the SQLite file doesn't exist or is empty.
- **`db/`** at the top level is the runtime bind-mount point. The SQLite file (`db/finally.db`) is created here by the backend and persists across container restarts. Deleting the file is the manual way to reset everything.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# OpenRouter API key for live LLM chat. Not needed when LLM_MOCK=true.
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Set to "true" for deterministic mock LLM responses (testing / no API key)
LLM_MOCK=false

# Stretch goal only (see §11): Massive (Polygon.io) API key for real market data.
# Ignored by the core build; the built-in simulator is always used.
MASSIVE_API_KEY=
```

### Behavior

- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (see §9) and never contacts OpenRouter
- If `LLM_MOCK` is not `true` and `OPENROUTER_API_KEY` is missing or empty → the app starts normally; `POST /api/chat` returns `503 {"detail": "LLM not configured"}` and the chat panel shows that message. Everything else works.
- In Docker the variables are passed with `docker run --env-file .env`. The backend also loads `.env` from the project root via `python-dotenv` **only for local `uv run` development**.
- `MASSIVE_API_KEY` is reserved for the stretch goal and has no effect in the core build.

---

## 6. Market Data

### One Interface, One Core Implementation

All market data flows through an abstract `MarketDataSource` interface with a single method contract: produce price ticks for a given set of tickers into the shared price cache. The core build ships one implementation, the **simulator**. A Massive REST client is a stretch goal (§11) that implements the same interface; nothing downstream (price cache, SSE, frontend) may depend on which source is active.

### Which Tickers Are Priced

The priced set is **`watchlist ∪ positions`**. A ticker the user removed from the watchlist but still holds keeps streaming so the portfolio can be valued. A ticker leaves the simulator only when it is in neither set.

### Ticker Validation

Tickers are uppercased and must match `^[A-Z]{1,5}$`. Anything else is rejected with `422`. There is no existence check — the simulator can price any symbol.

### Simulator

- Generates prices using geometric Brownian motion (GBM) with per-ticker drift and volatility
- Updates at ~500ms intervals
- Runs as an in-process background task — no external dependencies
- **Seed prices**: a built-in table of ~30 well-known tickers with realistic seeds (e.g., AAPL ~$190, GOOGL ~$175) and per-ticker drift/vol. Unknown tickers get a deterministic pseudo-random seed in the $20–$400 range (hash of the symbol) and default drift/vol.
- **Session open**: the seed price at process start is recorded as `session_open` and is the reference for "daily change %"
- **Restarts reset prices to seed.** This is accepted for a demo: a position bought at $250 may reopen with the ticker at $190. Do not treat it as a bug.
- **Second pass (not core)**: correlated moves across sector groups and occasional random 2–5% "events" for drama. Plain independent GBM per ticker is sufficient for the first build; these add no interface changes.

### Shared Price Cache

- The market data task writes to an in-memory price cache
- For each ticker the cache holds: `price`, `prev_price` (last tick), `session_open`, `timestamp`, and a ring buffer of the last ~600 ticks (~5 minutes) for chart seeding
- SSE streams and REST endpoints read from this cache; nothing reads the simulator directly
- This architecture supports future multi-user scenarios without changes to the data layer

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API
- **One event per tick containing all priced tickers** (not one event per ticker). On connect the first event is therefore a full snapshot, which also makes reconnects trivial.
- Event format:

  ```
  retry: 2000
  event: prices
  data: {"ts": "2026-10-14T12:00:00.500Z",
         "prices": [{"ticker": "AAPL", "price": 190.12, "prev_price": 190.05,
                     "session_open": 189.40, "change_pct": 0.38, "direction": "up"}, ...]}
  ```

  `direction` is `"up"`, `"down"` or `"flat"` relative to `prev_price`. `change_pct` is relative to `session_open`.
- The server sends an SSE comment line (`: ping`) every 15 seconds as a keepalive
- Client reconnection is automatic (EventSource built-in retry, hinted at 2s)

### Price History

`GET /api/prices/{ticker}/history` returns the ring buffer as `[{ts, price}, ...]` (oldest first). The frontend uses it to seed the main chart when a ticker is selected, then appends live SSE ticks. Sparklines remain frontend-only, accumulated since page load.

---

## 7. Database

### SQLite with Lazy Initialization

The backend checks for the SQLite database on startup (or first request). If the file doesn't exist or tables are missing, it creates the schema and seeds default data. This means:

- No separate migration step
- No manual database setup
- A fresh `db/` directory starts with a clean, seeded database automatically

### Conventions

- **Timestamps** are ISO-8601 UTC strings with a `Z` suffix (e.g., `2026-10-14T12:00:00.500Z`) everywhere: Python, SQLite, API, browser.
- **Concurrency**: request handlers, the snapshot task and the market data task all touch the database. Open the database in WAL mode and use short-lived connections per operation (or one connection guarded by an `asyncio.Lock`) to avoid `database is locked`.
- **Money is `REAL`.** Compare with a tolerance of `1e-6` dollars when validating (`cost <= cash + 1e-6`) and round to cents for display. Quantities are rounded to 4 decimals.

### Schema

All tables include a `user_id` column defaulting to `"default"`. This is hardcoded for now (single-user) but enables future multi-user support without schema migration.

**users_profile** — User state (cash balance)
- `id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `10000.0`)
- `created_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**positions** — Current holdings (one row per ticker per user)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL
- `updated_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart). Recorded every 30 seconds by a background task, and immediately after each trade execution.
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT (ISO timestamp)

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — the `actions` object from §9, including failed actions; null for user messages)
- `created_at` TEXT (ISO timestamp)

### Trade Semantics

- **Buy**: requires `quantity * price <= cash_balance + 1e-6`. Creates the position or updates it with a weighted new `avg_cost`.
- **Sell**: requires `quantity <= held quantity + 1e-6`. `avg_cost` is unchanged. When the remaining quantity is 0 (within tolerance) the `positions` row is **deleted**.
- **Realized P&L is not tracked or displayed.** The app shows unrealized P&L and total portfolio value; realized gains are implicit in cash.
- Every trade appends a `trades` row and records a `portfolio_snapshots` row.

### Default Seed Data

- One user profile: `id="default"`, `cash_balance=10000.0`
- Ten watchlist entries: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

### Reset

`POST /api/reset` deletes all positions, trades, snapshots and chat messages, restores `cash_balance` to 10000 and the default watchlist. It is not exposed in the UI; it exists for demos and E2E tests and is documented in the README. Deleting `db/finally.db` achieves the same thing offline.

---

## 8. API Endpoints

### Conventions

- All responses are JSON. Errors use FastAPI's `{"detail": "..."}` shape.
- `422` for malformed input (schema validation, bad ticker format, non-positive quantity).
- `400` for business-rule rejections with a human-readable detail, e.g. `"Insufficient cash: need $1,901.20, have $1,500.00"`, `"Insufficient shares: have 5, selling 10"`.
- `404` for a ticker not in the watchlist on `DELETE`.
- `503` from `/api/chat` when the LLM is not configured.

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates (format in §6) |
| GET | `/api/prices/{ticker}/history` | Last ~600 ticks for chart seeding: `[{ts, price}]` |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | `{cash_balance, total_value, unrealized_pnl, positions: [{ticker, quantity, avg_cost, current_price, market_value, unrealized_pnl, pnl_pct}]}` |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}`. Returns `{trade: {...}, portfolio: {...}}` where `portfolio` is the same object as `GET /api/portfolio`, so no follow-up fetch is needed |
| GET | `/api/portfolio/history` | Portfolio value snapshots `[{recorded_at, total_value}]`. Query `?limit=` (default 500, newest) and/or `?since=` ISO timestamp |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}` (validated per §6) |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send `{message}`, receive the complete response object defined in §9 |
| GET | `/api/chat/history` | Recent messages `[{id, role, content, actions, created_at}]`, `?limit=` (default 50) |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | `{"status": "ok", "market_data": "simulator", "llm": "live" \| "mock" \| "unconfigured", "db": "ok"}` — polled by the start scripts before opening the browser |
| POST | `/api/reset` | Reset to seed state (see §7) |

---

## 9. LLM Integration

When writing code to make calls to LLMs, use cerebras-inference skill to use LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with exact quantities and P&L, watchlist with live prices, total portfolio value)
2. Loads the **last 20 messages** from the `chat_messages` table, including the `actions` of previous assistant turns (so the model sees which earlier trades failed)
3. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
4. Calls the LLM **once** via LiteLLM → OpenRouter, requesting structured output, using the cerebras-inference skill
5. Parses the structured JSON response. If the response is not valid JSON or fails schema validation, retry once; if it fails again, use the raw text as `message` with no actions
6. Auto-executes any trades or watchlist changes specified in the response, recording per-action success or failure
7. Stores the user message and the assistant message (with the full `actions` object) in `chat_messages`
8. Returns the complete response to the frontend (no token-by-token streaming — Cerebras inference is fast enough that a loading indicator is sufficient)

**There is no second LLM call after action execution.** Failed actions are shown inline by the frontend with their error text, and because they are persisted in `actions`, the model sees them in the next turn's history.

### LLM Output Schema (what the model returns)

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "AAPL", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (optional): Array of trades to auto-execute. `quantity` is a number > 0 (fractional allowed). Each trade goes through the same validation as manual trades
- `watchlist_changes` (optional): Array of watchlist modifications, `action` is `"add"` or `"remove"`

### Chat API Response Schema (what `/api/chat` returns and `chat_messages.actions` stores)

```json
{
  "message": "...",
  "actions": {
    "trades": [
      {"ticker": "AAPL", "side": "buy", "quantity": 10, "price": 190.12, "status": "executed", "error": null},
      {"ticker": "TSLA", "side": "sell", "quantity": 50, "price": null, "status": "failed", "error": "Insufficient shares: have 5, selling 50"}
    ],
    "watchlist_changes": [
      {"ticker": "PYPL", "action": "add", "status": "executed", "error": null}
    ]
  }
}
```

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees, computing exact quantities from the provided context (e.g., "sell all" → the held quantity)
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON
- **Not claim a trade succeeded in `message`** — trades are validated after the response and may fail; phrase as "placing an order for…"

### LLM Mock Mode

When `LLM_MOCK=true`, the backend never contacts OpenRouter and instead applies deterministic rules to the user message:

- `buy <qty> <TICKER>` / `sell <qty> <TICKER>` (case-insensitive, any number of them) → the corresponding `trades`
- `add <TICKER>` / `remove <TICKER>` → the corresponding `watchlist_changes`
- Anything else → a canned portfolio summary built from the real portfolio context, no actions
- Every mock `message` is prefixed with `[mock] `

Actions still go through the real execution path, so E2E tests exercise real trade validation. This enables fast, free, reproducible tests, development without an API key, and CI/CD.

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watched tickers with: ticker symbol, current price (flashing green/red on change), daily change % (`change_pct` from the SSE event, vs. session open), and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, with at minimum price over time. Seeded from `GET /api/prices/{ticker}/history`, then extended by SSE ticks. Clicking a ticker in the watchlist selects it here.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by portfolio weight, colored by P&L (green = profit, red = loss). Empty state per §2.
- **P&L chart** — line chart showing total portfolio value over time, using data from `GET /api/portfolio/history`
- **Positions table** — tabular view of all positions: ticker, quantity, avg cost, current price, unrealized P&L, P&L %
- **Trade bar** — simple input area: ticker field, quantity field (accepts decimals), buy button, sell button. Market orders, instant fill. Errors from the API are shown inline.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history (loaded from `GET /api/chat/history` on page load), loading indicator while waiting for LLM response. Each action in `actions` is rendered inline as a confirmation chip: green for `executed`, red with the error text for `failed`.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance

### Where Live Values Are Computed

The frontend fetches `GET /api/portfolio` on page load and after every trade or chat response. Between those moments it recomputes header total, positions-table current prices, unrealized P&L and the heatmap **client-side** from the latest SSE prices. It does not poll `/api/portfolio`.

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`; handle the single `prices` event per tick as one state update
- **Charting: Recharts for everything** — line chart (main chart, P&L), `Treemap` (heatmap), and tiny `LineChart`s for sparklines. One library, SVG rendering is fine at 10–20 tickers × 2 updates/sec. Do not add a second charting library.
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme
- `next.config` for static export: `output: 'export'`, `images: { unoptimized: true }`, consistent `trailingSlash` setting matched by the FastAPI static mount

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves the static frontend files and all API routes on port 8000. **SPA fallback**: any path not under `/api` that does not match a static file returns `index.html`.

### Database Persistence (bind mount)

The SQLite database persists via a bind mount of the repo's `db/` directory:

```bash
docker run --rm -v "$(pwd)/db:/app/db" -p 8000:8000 --env-file .env --name finally finally
```

Students can see `db/finally.db`, back it up, or delete it to reset. (A named Docker volume is deliberately **not** used — it hides the file.)

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the bind mount, port mapping, and `--env-file .env`
- Polls `GET /api/health` until it returns `status: ok`, then prints the URL
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container
- Does NOT touch `db/` (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

### Stretch Goals (not part of the core build)

**Massive (Polygon.io) real market data.** A second `MarketDataSource` implementation activated when `MASSIVE_API_KEY` is set and non-empty:
- REST polling (not WebSocket); use the multi-ticker snapshot endpoint so the union of priced tickers is **one request per interval**
- Poll interval by tier: free tier 15s, paid tiers 2–15s
- `session_open` comes from the previous close, so "daily change %" is meaningful
- Caveats to document for users: free-tier data may be delayed or end-of-day only (verify against current Massive docs before relying on it), and prices are flat outside market hours — the UI will look dead on weekends. This is expected, not a bug.
- `/api/health` reports `"market_data": "massive"` when active

**Cloud deployment.** The container is designed to deploy to AWS App Runner, Render, or any container platform. A Terraform configuration for App Runner may be provided in a `deploy/` directory.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)** — the primary unit-test investment:
- Market data: simulator generates valid prices, GBM math is correct, seed table and unknown-ticker fallback, `session_open`/`change_pct`, ring buffer bounds, the simulator conforms to the abstract interface
- Portfolio: trade execution logic, weighted `avg_cost`, position deletion on full sell, tolerance handling, edge cases (selling more than owned, buying with insufficient cash, selling below avg cost reduces cash correctly)
- LLM: structured output parsing handles all valid schemas, retry-then-fallback on malformed responses, per-action success/failure recording, mock-mode command parsing
- API routes: correct status codes per §8 conventions, response shapes, error handling, `/api/reset`

**Frontend** — **pure functions only**: P&L math, formatters, the SSE payload reducer, mock-chip rendering logic. No component/DOM tests; everything visual is covered by Playwright.

### E2E Tests (in `test/`)

**Infrastructure**: `test/docker-compose.test.yml` spins up the app container plus a Playwright container. This keeps browser dependencies out of the production image. The test compose file mounts a **fresh, empty `db/` directory** (never the developer's), and the suite additionally calls `POST /api/reset` in `beforeAll` so every run starts from seed state.

**Environment**: Tests run with `LLM_MOCK=true`.

**Key Scenarios**:
- Fresh start: default watchlist appears, $10k balance shown, prices are streaming
- Add and remove a ticker from the watchlist (including a rejected invalid ticker)
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates; selling everything removes the row
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): `buy 5 AAPL` produces an inline executed chip; `sell 500 AAPL` produces an inline failed chip with the error
- SSE resilience (Chromium): `context.setOffline(true)` → status dot leaves green within 5s → `setOffline(false)` → status dot returns to green within 5s and prices resume

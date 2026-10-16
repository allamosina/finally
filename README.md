# FinAlly — AI Trading Workstation

FinAlly (Finance Ally) is an AI-powered trading workstation: live streaming prices, a simulated $10,000 portfolio, and an LLM chat assistant that can analyze positions and execute trades on your behalf. Think Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. The application is built entirely by coding agents working from the specification in [`planning/PLAN.md`](planning/PLAN.md).

## Status

Early build. The specification is complete. `backend/app/market/` (price cache and simulator) and a terminal demo exist; the FastAPI app, `frontend/`, `scripts/` and `test/` do not yet.

## What it does

- Streams simulated prices for a watchlist of tickers with green/red flash animations and sparklines
- Buys and sells fractional shares at market with instant fills and no fees
- Shows a portfolio heatmap, a portfolio value chart and a positions table with unrealized P&L
- Provides an AI chat assistant that reads your portfolio, suggests trades, and executes trades and watchlist changes from natural language

## Architecture

One Docker container, one port.

| Layer | Choice |
|---|---|
| Frontend | Next.js + TypeScript, static export, Tailwind, Recharts |
| Backend | FastAPI (Python, managed with `uv`) serving the API and the static frontend |
| Real-time data | Server-Sent Events at `/api/stream/prices` |
| Market data | Built-in geometric Brownian motion simulator |
| Database | SQLite at `db/finally.db`, bind-mounted for persistence |
| LLM | LiteLLM → OpenRouter (`openai/gpt-oss-120b` on Cerebras) with structured outputs |

## Running (once built)

1. Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`. Set `LLM_MOCK=true` instead to run without a key.
2. Start the container:

   ```bash
   ./scripts/start_mac.sh        # macOS / Linux
   .\scripts\start_windows.ps1   # Windows PowerShell
   ```

3. Open `http://localhost:8000`.

Stop with `./scripts/stop_mac.sh` or `.\scripts\stop_windows.ps1`. Data persists in `db/`. To reset, call `POST /api/reset` or delete `db/finally.db`.

### Market simulator demo

The price simulator (`backend/app/market/`) can be watched on its own in a terminal, no Docker or dependencies needed:

```bash
python3 backend/demo_market.py              # live tape, Ctrl+C to stop
python3 backend/demo_market.py --seconds 20 --seed 42
python3 backend/demo_market.py --json       # the SSE payload per tick
```

It shows seed prices, live GBM ticks with sparklines, a `prime()` / `set_tickers()` sequence, and ends with the source's `health()` and a contract checklist. See `--help` for all options.

## Repository layout

```
planning/          Project specification (PLAN.md) and agent review log (REVIEW.md)
.claude/           Agents, commands, skills and settings for Claude Code
independent-reviewer/  Claude Code plugin that runs a Codex review on every stop
frontend/          Next.js app (planned)
backend/           FastAPI app (planned); market simulator package and demo exist
scripts/           Start/stop scripts (planned)
test/              Playwright E2E tests (planned)
db/                Runtime SQLite bind mount (planned)
```

## Development workflow

Agents read `planning/PLAN.md` as the shared contract. After each change, an independent Codex review is appended to `planning/REVIEW.md`.

## License

MIT. See [LICENSE](LICENSE).

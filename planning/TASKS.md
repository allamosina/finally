# FinAlly Build — Task Board

Team: `finally-build`. Lead maintains this file; teammates do not edit it.
Status values: `todo` · `in-progress` · `blocked` · `review` · `done`.

## Wave 1 (parallel, started 2026-10-16)

| ID | Owner | Task | Status | Notes |
|---|---|---|---|---|
| W1-DB | db-engineer | Schema, `init_db`, seed, repo functions, `execute_trade` transaction, `reset()`, unit tests in `backend/tests/db/` | done | Everyone depends on this; target done first |
| W1-BE | backend-engineer | `pyproject.toml` deps, `main.py` lifespan wiring market source, SSE route, history route, health route; fix the two open simulator findings (`set_tickers` primed-only drop, `drop()` version bump); stub repo until W1-DB lands | done | Announce "backend deps synced" first so others can `uv run` |
| W1-LLM | llm-engineer | Output schema, system prompt, mock parser, response parsing with retry-then-fallback, `status()`, unit tests in `backend/tests/llm/` | done | Action executor waits on W2-BE portfolio service |
| W1-FE | frontend-engineer | Next.js static-export project, Tailwind, Recharts, layout, SSE reducer, watchlist with flashes + sparklines, main chart, trade bar, header; mock API; pure-function unit tests | done | Codes against PLAN §8 from day one |
| W1-OPS | devops-engineer | `Dockerfile`, `.dockerignore`, `.env.example`, start/stop scripts (mac + windows), `db/.gitkeep`, gitignore entries for `db/*.db*` | done (unverified: Docker blocked) | Build against whatever exists; rebuild as others land |
| W1-QA | integration-tester | Playwright project in `test/`, `test/docker-compose.test.yml` (with devops), spec skeletons for every PLAN §12 scenario, `beforeAll` reset, specs `test.skip` until features exist | done | |

## Wave 2 (blocked on wave 1)

| ID | Owner | Task | Status | Blocked on |
|---|---|---|---|---|
| W2-BE | backend-engineer | Portfolio + watchlist services and routes, snapshot task (30 s), reset route; run backend with `STATIC_DIR=../frontend/out` and confirm SPA loads; thin `/api/chat` + `/api/chat/history` routes | done (static serving verified via ASGI; browser check by user) | — |
| W2-LLM | llm-engineer | Action executor, `chat()` end to end (route is backend-engineer's) | done | verified against real portfolio service in mock mode, 41 tests |
| W2-FE | frontend-engineer | Positions table, heatmap, P&L chart, chat panel with action chips, connection status dot; switch mocks to live API as route groups are announced | in-progress | — |

## Wave 3 (integration)

| ID | Owner | Task | Status | Blocked on |
|---|---|---|---|---|
| W3-OPS | devops-engineer | Full image build, `start_mac.sh` end to end, health poll, browser opens | todo | W2-* |
| W3-QA | integration-tester | Unskip specs, run suite against compose stack with `LLM_MOCK=true`, report failures to owners, maintain `test/ISSUES.md` | todo | W3-OPS |
| W3-ALL | everyone | Fix what the tester reports before starting anything new | todo | W3-QA |
| W3-REVIEW | integration-tester | Final review after suite is green; lead appends it to `planning/REVIEW.md` | todo | W3-QA green |

## Log

- 2026-10-16: board created; wave 1 assigned to all six teammates.
- 2026-10-16 20:55: sandbox blocks `uv sync`/`uv lock` (uv panics reading macOS proxy config) and the Docker socket. Lead installed backend deps into `backend/.venv` with pip; teammates run tests with `uv run --no-sync pytest`. Open: user must run `cd backend && uv lock` outside the sandbox; Docker build/run deferred to wave 3 or the user. W1-QA: Playwright skeleton lists 33 specs, tsc clean.
- 2026-10-16 21:00: backend suite 123 passed (db 38). W1 done for db, backend, llm, devops, tester; frontend still in progress. W2-BE and W2-LLM assigned.
- 2026-10-16 21:10: W2-LLM done; chat() verified end to end in mock mode against the real portfolio service.
- 2026-10-16 21:20: live OpenRouter call verified by llm-engineer (structured output accepted, cerebras provider, schema parse, watchlist action executed). LLM module fully done.
- 2026-10-16 21:25: W2-BE done, backend suite 168 passed. Only W1-FE/W2-FE outstanding before wave 3.
- 2026-10-16 21:30: backend suite 173 passed with no env vars (tests/conftest.py guards). Chat route: 503 unconfigured, 502 on transport error, mock chat verified through the real route. SSE sends snapshot on connect and empty-set heartbeat every 1 s.
- 2026-10-16 21:40: frontend/out builds (next build --webpack), 31 frontend unit tests pass; backend verified static serving + SPA fallback via ASGI. User told how to run the app on :8000.
- 2026-10-16 21:50: wave 1 committed as 1064d9d (105 files). W2-FE in progress; all other W1/W2 tasks done. Wave 3 waits on W2-FE.

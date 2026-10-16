# Change Review Log

Appended by the Stop hook after each agent turn. Newest entry last.

---

## 2026-10-15 — Review of commit da8006b (6b568a9..da8006b)

**Scope**: PLAN.md rewrite, three new planning docs (MARKET_INTERFACE.md, MARKET_SIMULATOR.md, MASSIVE_API.md), README expansion, `.claude/settings.json` change, removal of `change-reviewer` agent and `doc-review` command. Docs only; no code.

### Must fix (contradictions agents will trip over)

1. **PLAN.md and the market docs disagree on whether Massive is in the core build.**
   PLAN §3, §5 and §6 now say the simulator is the only core source and `MASSIVE_API_KEY` "has no effect in the core build". MARKET_INTERFACE.md says the opposite throughout: the intro ("two implementations"), §8 `build_source()` selects Massive when the key is set, §10 tells `.env.example` to list five Massive/sim variables, and §11 requires a conformance suite "parametrized over both sources". MARKET_SIMULATOR.md's intro also calls the simulator "the default used whenever `MASSIVE_API_KEY` is not set". A backend agent reading these three files will build the Massive client as core work. Pick one. Recommended: keep PLAN's decision and add a banner to MARKET_INTERFACE.md §7, §8 (Massive branch), §10 and §11 marking those parts as stretch, with `build_source()` returning the simulator unconditionally in core.

2. **PLAN §11 stretch goal still states "free tier 15s" polling of the snapshot endpoint.** MASSIVE_API.md §2 and §7 establish that the Basic plan has no snapshot endpoint and returns end-of-day closes only via grouped daily bars. MASSIVE_API.md §7 explicitly lists this as a PLAN.md correction, but the correction was not applied in this commit. Update PLAN §11 to: Basic = end-of-day mode, 15-min poll of grouped daily bars; Starter/Developer = 15 s snapshot, 15-min delayed; Advanced = 2 s.

3. **`/api/health` shape differs between documents.** PLAN §8 defines `"market_data": "simulator" | "massive"`. MARKET_INTERFACE.md §7–§9 emits `"massive:snapshot"`, `"massive:eod"`, `"massive:error"`, a `"market_data_note"` key, and a nested `"market": source.health()` object. The start scripts and E2E tests will key off this field. Align PLAN §8 with the richer shape or trim MARKET_INTERFACE.md.

### Should fix (gaps between contract and design)

4. **Two API behaviours exist only in MARKET_INTERFACE.md and not in PLAN §8.** `POST /api/portfolio/trade` returning `503 {"detail": "Price unavailable for XYZ"}` when `prime()` yields nothing, and `GET /api/prices/{ticker}/history` returning `[]` with 200 for an unknown ticker. Both are reasonable; add them to PLAN §8 Conventions so the API agent and the test agent see them.

5. **Single-worker requirement is not in PLAN.** MARKET_INTERFACE.md §4 correctly notes the cache is process-local and demands `--workers 1`. PLAN §11's Dockerfile sketch should say so in the `CMD`, otherwise a well-meaning agent may add workers and the SSE stream will show different prices per connection.

6. **Ordering dependency for buys of unwatched tickers is implicit.** MARKET_INTERFACE.md §5 relies on the trade service calling `prime()` before pricing and the app calling `set_tickers()` after the position is committed. Between those two calls the primed ticker sits in the cache but not in `_tickers`, so the simulator never advances it. Document the sequence in the trade-service section (prime → price inside transaction → commit → `set_tickers(watchlist ∪ positions)`).

7. **`PriceCache.drop()` bypasses the Condition and does not bump `_version`.** Clients learn of a removed ticker only on the next `apply()`. Harmless at 500 ms simulator cadence; in Massive EOD mode a removed ticker lingers in every connected client for up to 15 minutes. Either bump the version under the lock or state it as accepted.

8. **README describes infrastructure that is not in the repo.** The layout lists an `independent-reviewer/` directory and the workflow section says "an independent Codex review is appended to `planning/REVIEW.md`". Neither the directory nor a Codex integration exists; `settings.json` enables `independent-reviewer@alla-tools` from an external marketplace and the review hook is a Claude `agent` hook. Either vendor the plugin into the repo or reword README to say the review is produced by the Stop hook in `.claude/settings.json`.

### Process

9. **The Stop hook prompt cannot review a commit.** It says "review all changes since last commit". When the user's request is itself "commit", the working tree is clean by the time the hook runs, which is why this entry was written manually after the hook reported failure. Suggested prompt: "Review the uncommitted changes in the working tree, or if the tree is clean, the changes in the most recent commit, and append the result to planning/REVIEW.md."

10. **REVIEW.md is now tracked and will grow with every turn.** PLAN §4 lists it in the tree, so tracking is intended. Consider a periodic prune or a size cap in the hook prompt.

### Verified and fine

- MARKET_SIMULATOR.md §2 numbers check out: with `sigma_tick = 0.0005`, 1 min ≈ 0.55 %, 5 min ≈ 1.22 %, 1 h ≈ 4.24 %; mean-reversion half-life at `κ = 1e-4` is ln 2 / κ ≈ 6,931 ticks ≈ 58 min.
- `gbm_step()` is the exact discrete-time GBM with Δt folded into per-tick parameters; the `-0.5·σ²` Itô correction is present.
- SHA-256-based `hashed_seed_price()` and per-ticker RNG seeding give the cross-process determinism PLAN §6 asks for; the test in §8 that compares across a subprocess will catch any regression to `hash()`.
- One `cache.apply()` per tick matches PLAN §6's "one SSE event per tick with all tickers"; the SSE loop in MARKET_INTERFACE.md §9 uses the `Condition` rather than polling and emits `: ping` on a 15 s timeout as PLAN requires.
- The LLM output schema vs chat response schema split in PLAN §9, and the "no second LLM call" rule, are consistent with the `chat_messages.actions` column definition in §7 and the chip rendering in §10.
- PLAN §12 E2E scenario `sell 500 AAPL` producing "Insufficient shares: have 5, selling 500" depends on the earlier `buy 5 AAPL` step in the same run; this is fine given `POST /api/reset` in `beforeAll`, but the two steps must stay in one ordered spec.
- `.claude/settings.json` reformat is whitespace plus the `enabledPlugins` addition; the deleted agent and command files are superseded by that plugin.

---

## 2026-10-16 — Review of uncommitted changes (working tree vs a58ea22)

**Scope**: first backend code. New `backend/` with a minimal uv project (`pyproject.toml`, `uv.lock`, no dependencies), the market data package `backend/app/market/` (`types.py`, `cache.py`, `base.py`, `config.py`, `seeds.py`, `gbm.py`, `simulator.py`, `__init__.py`) implemented from MARKET_INTERFACE.md and MARKET_SIMULATOR.md, and a terminal demo `backend/demo_market.py`. README gains a "Market simulator demo" section and an updated status line. Also untracked: `AGENTS.md`, `.agents/skills/cerebras/SKILL.md`, `.codex/config.toml` (Codex CLI setup; not produced by this turn).

Verified by running: `python3 backend/demo_market.py` in plain, JSON and live-table modes and via `uv run`; all five end-of-run contract checks pass; a `MASSIVE_API_KEY` set in the environment now logs a warning and still yields the simulator.

### Fixed during this turn

1. **`build_source()` raised `NotImplementedError` when `MASSIVE_API_KEY` was set.** PLAN §5 says the key "is ignored by the core build; the built-in simulator is always used". A student with a stray key in `.env` would have had the app fail at startup. Changed to log a warning and return the simulator. MARKET_INTERFACE.md §8 still shows the two-branch version; see previous entry, item 1 (still open).
2. **README status said `backend/` does not exist.** Updated to describe what exists now.

### Should fix (code)

3. **`set_tickers()` never drops a ticker that was only ever `prime()`d.** `removed` is computed from `self._tickers`, which `prime()` does not touch, so a ticker primed for a failed buy stays in the cache (and in every SSE event) forever, unticked. MARKET_INTERFACE.md §5 prose says it "ages out at the next `set_tickers()`", so the spec's own code and prose disagree. Recommended: in `base.set_tickers()` also drop `self.cache.tickers() - tickers`. The demo labels such rows "primed only, not ticking", so the behaviour is visible. (This is the spec code transcribed; it should be fixed in both places.)
4. **`PriceCache.drop()` still does not bump `_version` or notify waiters** (carried over from the previous entry, item 7). The demo's live table only loses a dropped ticker on the next tick; harmless for the simulator, wrong for EOD mode.
5. **Demo exit on Windows after Ctrl+C skips the summary.** `loop.add_signal_handler` raises `NotImplementedError` there, so Ctrl+C surfaces as `KeyboardInterrupt` from `asyncio.run`, the `finally` runs but `print_summary()` is after the `try`. Move the summary into `finally` or catch inside `run()`. Demo-only, low priority.
6. **`demo_market.py` monkeypatches private `_fetch_now` and `cache.apply` to count calls.** Acceptable for a demo; do not copy this into tests. The conformance suite in MARKET_INTERFACE.md §11 should spy via `unittest.mock` on `cache.apply` only.
7. **`pyproject.toml` has no dependencies and `package = false`.** Fine for now; the FastAPI agent will add `fastapi`, `uvicorn`, `python-dotenv`, `litellm`, `pydantic` and regenerate `uv.lock`. `requires-python = ">=3.12"` matches the PLAN §11 base image.

### Should fix (docs and process)

8. **PLAN §8 `/api/health` shape vs `source.health()`** (previous entry, item 3) is now concrete: `SimulatorSource.health()` returns `{name, tickers, ticks, tick_ms, last_tick_ms, seeded}`. PLAN §8 should state whether this is nested under `"market"` as MARKET_INTERFACE.md §9 says.
9. **`AGENTS.md` is a byte-for-byte copy of `CLAUDE.md` including the `@planning/PLAN.md` include line.** Codex does not expand `@file` includes, so Codex agents see a one-line pointer rather than the plan. Either inline the plan or replace the include with a plain "read planning/PLAN.md first" instruction.
10. **`.agents/skills/cerebras/SKILL.md` duplicates `.claude/skills/cerebras/SKILL.md`.** Two copies will drift. Symlink one to the other or note which is canonical.
11. **The Stop hook prompt still reviews "changes since last commit"** (previous entry, item 9). This entry was written by the main agent after the hook reported the condition unmet. Also, `.claude/settings.json` references `independent-reviewer@alla-tools` and README still describes a Codex review; neither is what produced this entry.
12. **An empty `backend/.claude/.cc-writes/` directory appeared** when the harness changed working directory into `backend/`. Git ignores empty directories so it is invisible to the repo, but a `backend/.claude/` folder may confuse a reader. Safe to delete.

### Verified and fine

- `gbm_step()`, `rng_for()`, `hashed_seed_price()`, `spec_for()` and the `SEEDS` table match MARKET_SIMULATOR.md §2–§5 exactly; `hashed_seed_price("ZZZZ")` = 243.33 and `("XYZQ")` = 336.16 are stable across runs.
- Determinism holds as specified: with `--seed 7`, AAPL's path is identical whether the ticker set is the ten-ticker watchlist or `{AAPL, XYZQ}` (per-ticker RNG seeded from `(seed, ticker)`).
- One `cache.apply()` per tick with every ticker in the batch; the demo's spy confirms `applies == ticks + prime calls` on every run. SSE will get one event per tick as PLAN §6 requires.
- Drift-free cadence: `_run()` schedules against `monotonic()` targets; measured rate at `--tick-ms 200` was 5.0–5.4/s including startup.
- `session_open` is fixed at the seed price per ticker for the process lifetime; `change_pct` and `direction` are computed on `Quote` as specified. History is oldest-first and `deque(maxlen=600)`.
- Prices are rounded to 4 decimals in the cache in both `_tick()` and `_fetch_now()` (the spec only rounds in `_tick()`; rounding the prime tick too keeps the first history entry consistent with the rest).
- `set_tickers()` in the simulator forgets `_SimState` for dropped tickers, so re-adding re-seeds at the seed price as MARKET_SIMULATOR.md §6 says.
- `to_sse_payload()` in the demo emits exactly the PLAN §6 event shape (`ts` ISO-8601 `Z`, `prices[]` with `ticker, price, prev_price, session_open, change_pct, direction`), which the SSE route can lift as-is.
- The package imports without FastAPI or the database, as MARKET_INTERFACE.md §2 requires.

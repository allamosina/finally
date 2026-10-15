# Massive API Reference for FinAlly

Research notes on the Massive market-data API (formerly Polygon.io), scoped to what FinAlly needs: current prices for a small set of US stock tickers, plus a daily reference price for "change %". Researched 2026-10-15 against the official docs at `massive.com/docs`. Verify plan details against `massive.com/pricing` before relying on them; pricing and entitlements change.

Related documents: [MARKET_INTERFACE.md](MARKET_INTERFACE.md) (how FinAlly wraps this API behind `MarketDataSource`) and [MARKET_SIMULATOR.md](MARKET_SIMULATOR.md) (the fallback when no key is set).

---

## 1. Essentials

| Item | Value |
|---|---|
| REST base URL | `https://api.massive.com` (`https://api.polygon.io` still works during the transition) |
| WebSocket, real-time | `wss://socket.massive.com/stocks` |
| WebSocket, 15-min delayed | `wss://delayed.massive.com/stocks` |
| Auth, header form (preferred) | `Authorization: Bearer <API_KEY>` |
| Auth, query form | `?apiKey=<API_KEY>` |
| Official Python client | `pip install -U massive` → `from massive import RESTClient` (Python ≥ 3.9) |
| Env var the client reads | `MASSIVE_API_KEY` (read at import time, not per instantiation) |
| Response envelope | `{"status": "OK", "request_id": "...", "results": [...] | "tickers": [...], "count": n}` |
| Timestamps | Bars: Unix **milliseconds**. Trades/quotes and `updated`: Unix **nanoseconds**. Market status: RFC 3339 |
| Tickers | Case-sensitive, uppercase for US stocks (`AAPL`). Other asset classes use prefixes (`O:`, `C:`, `X:`, `I:`) |

Existing Polygon.io API keys remain valid. The legacy `polygon-api-client` package is still supported for a transition period, but new code should use `massive`.

---

## 2. Plans and entitlements (this decides the design)

| Plan | Price | Calls/min | Recency | Snapshots | WebSocket | Prev-day bar | Grouped daily |
|---|---|---|---|---|---|---|---|
| Stocks Basic | $0 | **5** | **End of day** | **No** | **No** | Yes | Yes |
| Stocks Starter | $29/mo | Unlimited | 15-min delayed | Yes | Yes | Yes | Yes |
| Stocks Developer | $79/mo | Unlimited | 15-min delayed | Yes | Yes | Yes | Yes |
| Stocks Advanced | $199/mo | Unlimited | Real-time | Yes | Yes | Yes | Yes |
| Stocks Business | Custom | Unlimited | Real-time | Yes + FMV | Yes + FMV | Yes | Yes |

Three consequences for FinAlly:

1. **The free tier has no snapshot endpoint.** PLAN.md §11 assumes "free tier 15s polling of the multi-ticker snapshot". That will fail with an entitlement error. On Basic, the only multi-ticker price source is the grouped daily bars endpoint, which returns the previous completed trading day's close. Prices will be flat all day and only move once per day.
2. **"Live" prices need Starter or above**, and even then they are 15 minutes delayed until Advanced.
3. **Basic's 5 calls/min is tight.** One grouped-daily call per poll fits easily; per-ticker calls for 10+ tickers do not.

Entitlement failures appear two ways: as an HTTP `403` with `{"status": "NOT_AUTHORIZED", "message": "..."}` for an endpoint the plan lacks, and as **per-row errors inside an HTTP 200** on the unified snapshot (`"error": "NOT_ENTITLED"`). Code must check both.

---

## 3. Endpoints FinAlly cares about

### 3.1 Unified Snapshot — `GET /v3/snapshot` (primary, paid plans)

The best fit for "current price for N tickers in one request". Up to **250 tickers** per call via `ticker.any_of`. Returns present state only; no history.

| Query param | Notes |
|---|---|
| `ticker.any_of` | Comma-separated, max 250. Omit to page through everything (don't) |
| `type` | `stocks` to exclude other asset classes |
| `limit` | Default **10**, max **250**. **Set this explicitly** or you get 10 results back for 11+ tickers |
| `sort`, `order` | Optional ordering |

```bash
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v3/snapshot?ticker.any_of=AAPL,MSFT,NVDA&type=stocks&limit=250"
```

Response (abbreviated, one good row and one bad row):

```json
{
  "status": "OK",
  "request_id": "abc123",
  "results": [
    {
      "ticker": "AAPL",
      "type": "stocks",
      "name": "Apple Inc.",
      "market_status": "open",
      "last_trade":  {"price": 190.12, "size": 100, "sip_timestamp": 1760540400123456789, "timeframe": "DELAYED"},
      "last_quote":  {"bid": 190.10, "ask": 190.14, "midpoint": 190.12, "timeframe": "DELAYED"},
      "last_minute": {"open": 190.05, "high": 190.15, "low": 190.01, "close": 190.12, "volume": 61000, "vwap": 190.08},
      "session": {
        "open": 189.40, "high": 191.02, "low": 188.90, "close": 190.12,
        "previous_close": 189.00, "change": 1.12, "change_percent": 0.59, "volume": 31000000
      }
    },
    {"ticker": "TSLAAPL", "error": "NOT_FOUND", "message": "Ticker not found."}
  ]
}
```

Field semantics that matter:

- `market_status`: `open`, `closed`, `early_trading`, `late_trading`.
- `last_trade.price` is the freshest price your plan allows. `timeframe` tells you `REAL-TIME` or `DELAYED`.
- `session.previous_close` is the right reference for daily change %. `session.change_percent` is precomputed against it.
- `session.close` is the latest price for the session (updates intraday).
- Rows can carry `error` instead of data: `NOT_FOUND` (bad symbol) or `NOT_ENTITLED` (plan lacks it). HTTP status is still 200.

**Price selection order** for a row: `last_trade.price` → `last_minute.close` → `session.close` → `session.previous_close`. Record which one was used so the UI can show staleness.

Python client: `client.list_universal_snapshots(type="stocks", ticker_any_of=[...], limit=250)` returns an iterator of `UniversalSnapshot` models.

### 3.2 Full Market Snapshot — `GET /v2/snapshot/locale/us/markets/stocks/tickers` (paid plans, alternative)

Older endpoint. Same entitlement as 3.1. Accepts `?tickers=AAPL,MSFT` to filter; with no filter it returns the whole market (thousands of rows). Prefer 3.1; keep this as a fallback if 3.1 misbehaves.

```bash
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT"
```

```json
{
  "count": 2, "status": "OK",
  "tickers": [
    {
      "ticker": "AAPL",
      "day":     {"o": 189.62, "h": 191.02, "l": 188.90, "c": 190.12, "v": 31000000, "vw": 190.01},
      "prevDay": {"o": 188.10, "h": 189.80, "l": 187.50, "c": 189.00, "v": 48000000, "vw": 188.70},
      "min":     {"o": 190.05, "h": 190.15, "l": 190.01, "c": 190.12, "v": 61000, "vw": 190.08, "n": 410, "t": 1760540400000},
      "lastTrade": {"p": 190.12, "s": 100, "t": 1760540400123456789, "x": 10},
      "todaysChange": 1.12, "todaysChangePerc": 0.59,
      "updated": 1760540400123456789
    }
  ]
}
```

Snapshot data is **cleared daily at 3:30 AM ET** and repopulates as exchanges report from ~4:00 AM ET. Early in the morning `day` may be empty and `lastTrade` may be yesterday's.

Python client: `client.get_snapshot_all("stocks", tickers=["AAPL", "MSFT"])`. Single ticker: `client.get_snapshot_ticker("stocks", "AAPL")` → `GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}`.

### 3.3 Grouped Daily Bars — `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` (all plans, the Basic-tier workhorse)

One request returns one OHLC bar for **every** US stock that traded on `date` (12,000+ rows). This is the only way to get prices for many tickers in one call on the Basic plan.

| Param | Notes |
|---|---|
| `date` (path) | `YYYY-MM-DD`. A weekend, holiday, or not-yet-published day returns `resultsCount: 0` with `status: OK` |
| `adjusted` | Default `true` (split-adjusted) |
| `include_otc` | Default `false` |

```bash
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/2026-10-14?adjusted=true"
```

```json
{
  "status": "OK", "adjusted": true, "queryCount": 11234, "resultsCount": 11234, "request_id": "...",
  "results": [
    {"T": "AAPL", "o": 189.62, "h": 191.02, "l": 188.90, "c": 190.12, "v": 31000000, "vw": 190.01, "n": 410000, "t": 1760472000000},
    {"T": "MSFT", "o": 415.10, "h": 418.00, "l": 413.20, "c": 417.33, "v": 20000000, "vw": 416.10, "n": 300000, "t": 1760472000000}
  ]
}
```

Notes:

- `t` is the Unix-ms timestamp of the bar window (one per trading day).
- On Basic, "today" is not available until after the close and the end-of-day publish. The practical algorithm is: try today, then walk back one calendar day at a time (max 7) until `resultsCount > 0`. Two bars from consecutive trading days give you `close` (current price) and `previous close` (reference).
- Response is ~1–2 MB. Fetch it at most once every few minutes; the data only changes once per day. Filter it down to the watched tickers immediately and discard the rest.

Python client: `client.get_grouped_daily_aggs("2026-10-14", adjusted=True)` → `List[GroupedDailyAgg]`.

### 3.4 Previous Day Bar — `GET /v2/aggs/ticker/{ticker}/prev` (all plans)

Previous trading day's OHLC for one ticker. Use for a one-off reference price (e.g. seeding `session_open` for a newly added ticker) rather than polling: on Basic it costs one of your 5 calls/min per ticker.

```bash
curl -H "Authorization: Bearer $MASSIVE_API_KEY" "https://api.massive.com/v2/aggs/ticker/AAPL/prev?adjusted=true"
```

```json
{
  "ticker": "AAPL", "status": "OK", "adjusted": true, "queryCount": 1, "resultsCount": 1, "request_id": "...",
  "results": [{"T": "AAPL", "o": 188.10, "h": 189.80, "l": 187.50, "c": 189.00, "v": 48000000, "vw": 188.70, "t": 1760385600000, "n": 520000}]
}
```

Python client: `client.get_previous_close_agg("AAPL")` → `PreviousCloseAgg` with `.close`, `.open`, `.timestamp`.

### 3.5 Market Status — `GET /v1/marketstatus/now` (all plans)

Tells the poller whether to bother polling fast.

```json
{
  "market": "open",
  "serverTime": "2026-10-15T10:12:37-04:00",
  "earlyHours": false,
  "afterHours": false,
  "exchanges": {"nasdaq": "open", "nyse": "open", "otc": "open"},
  "currencies": {"crypto": "open", "fx": "open"}
}
```

`market` is one of `open`, `closed`, `extended-hours`. US sessions: pre-market 4:00–9:30 ET, regular 9:30–16:00 ET, after-hours 16:00–20:00 ET.

### 3.6 Date-range bars — `GET /v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}` (all plans, history varies)

Not needed for the core build. Could seed the main chart with real intraday minute bars on paid plans (`/range/1/minute/2026-10-15/2026-10-15`). Basic allows 2 years of daily history. Python: `client.list_aggs("AAPL", 1, "minute", "2026-10-15", "2026-10-15")`.

---

## 4. WebSocket (reference only; not used in the core build)

Starter and above. Connect, authenticate, subscribe, then receive JSON arrays of events.

```
→ {"action":"auth","params":"<API_KEY>"}
← [{"ev":"status","status":"auth_success","message":"authenticated"}]
→ {"action":"subscribe","params":"AM.AAPL,AM.MSFT"}
← [{"ev":"AM","sym":"AAPL","v":4110,"av":9470157,"op":189.62,"vw":190.08,"o":190.05,"c":190.12,"h":190.15,"l":190.01,"a":190.01,"z":44,"s":1760540400000,"e":1760540460000}]
```

Channels: `T` trades, `Q` quotes, `A` per-second bars, `AM` per-minute bars, `LULD`, `FMV` (Business only). `AM.*` subscribes to all tickers. No bar is emitted for a minute with no trades.

Python: `WebSocketClient(api_key=..., subscriptions=["AM.AAPL"]).run(handle_msg=...)` is blocking; there is also an async variant in the client package.

Why REST polling instead for FinAlly: one-way SSE fan-out from a polled cache is simpler, polling cost is trivial at 10–30 tickers, and the WebSocket adds reconnect/state complexity for no visible benefit at 15-minute delay. Revisit only on an Advanced plan.

---

## 5. Errors, limits, timing

| Situation | What you see | Handling |
|---|---|---|
| Missing/invalid key | HTTP 401/403, `{"status": "ERROR" | "NOT_AUTHORIZED", "message": "..."}` | Fail fast at startup; log; fall back to simulator |
| Endpoint not in plan | HTTP 403, `"status": "NOT_AUTHORIZED"` | Switch to end-of-day mode (grouped daily) |
| Ticker not in plan (unified snapshot) | HTTP 200, row `{"ticker": "...", "error": "NOT_ENTITLED"}` | Treat row as missing |
| Bad ticker | HTTP 200, row `{"error": "NOT_FOUND", "message": "Ticker not found."}` | Keep last known price or mark unavailable |
| Rate limit (Basic: 5/min) | HTTP 429 | Exponential backoff starting at 60 s; never retry in a tight loop |
| Transient server error | HTTP 5xx | Retry with jittered backoff; keep serving last cached prices |
| Weekend/holiday/early morning | `resultsCount: 0` or stale `updated` | Walk back to last trading day; show prices as flat; this is expected |

Other facts:

- Massive does not document a `Retry-After` header for 429. Assume none and back off on a fixed schedule.
- The official client raises `BadResponse(body_text)` for any non-200; it does not parse the error body. If using it, catch `BadResponse` and inspect `str(e)` for `NOT_AUTHORIZED`.
- Official client defaults: `connect_timeout=10.0`, `read_timeout=10.0`, `retries=3`, `pagination=True`, synchronous (urllib3). In FastAPI's event loop it must be called via `asyncio.to_thread`. See §6 for why FinAlly uses `httpx` directly instead.
- Snapshots reset at 3:30 AM ET. Between then and the first trade of the day, `day` is empty and `session.close` may be null.
- Paid-tier intraday data is 15 minutes delayed except on Advanced. The `timeframe` field on trades/quotes says which.

---

## 6. Recommended usage for FinAlly

**Use `httpx.AsyncClient` directly, not the `massive` package.** The surface we need is two GET endpoints with Bearer auth and JSON bodies. `httpx` is already natural in an async FastAPI app, needs no thread hopping, makes mocking trivial in tests, and avoids a dependency whose API key is read at import time.

```python
# backend/app/market/massive_client.py
import asyncio
import datetime as dt
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)
BASE = "https://api.massive.com"


@dataclass(frozen=True)
class MassiveQuote:
    ticker: str
    price: float
    previous_close: float | None
    as_of_ms: int            # when the price was observed, Unix ms
    source: str              # "last_trade" | "last_minute" | "session_close" | "eod_close"


class NotEntitled(Exception):
    """The plan does not include this endpoint."""


class MassiveClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None):
        self._http = http or httpx.AsyncClient(
            base_url=BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params) -> dict:
        r = await self._http.get(path, params=params)
        if r.status_code in (401, 403):
            raise NotEntitled(r.text)
        if r.status_code == 429:
            raise httpx.HTTPStatusError("rate limited", request=r.request, response=r)
        r.raise_for_status()
        return r.json()

    # --- paid plans: one request for up to 250 tickers --------------------
    async def snapshot(self, tickers: list[str]) -> dict[str, MassiveQuote]:
        if not tickers:
            return {}
        body = await self._get(
            "/v3/snapshot",
            **{"ticker.any_of": ",".join(sorted(tickers)), "type": "stocks", "limit": 250},
        )
        out: dict[str, MassiveQuote] = {}
        for row in body.get("results", []):
            if "error" in row:
                log.warning("snapshot %s: %s", row.get("ticker"), row["error"])
                continue
            q = _quote_from_snapshot_row(row)
            if q:
                out[q.ticker] = q
        return out

    # --- all plans: previous completed trading day, all US stocks ---------
    async def grouped_daily(self, day: dt.date) -> dict[str, dict]:
        body = await self._get(
            f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}", adjusted="true"
        )
        return {row["T"]: row for row in body.get("results", [])}

    async def latest_eod(self, tickers: set[str]) -> dict[str, MassiveQuote]:
        """Walk back from today to find the last two trading days; close = price, prior close = reference."""
        bars: list[dict[str, dict]] = []
        day = dt.datetime.now(dt.timezone.utc).date()
        for _ in range(10):
            rows = await self.grouped_daily(day)
            if rows:
                bars.append(rows)
                if len(bars) == 2:
                    break
            day -= dt.timedelta(days=1)
        if not bars:
            return {}
        latest, prior = bars[0], (bars[1] if len(bars) > 1 else {})
        out = {}
        for t in tickers:
            if t in latest:
                out[t] = MassiveQuote(
                    ticker=t,
                    price=latest[t]["c"],
                    previous_close=prior.get(t, {}).get("c"),
                    as_of_ms=latest[t]["t"],
                    source="eod_close",
                )
        return out


def _quote_from_snapshot_row(row: dict) -> MassiveQuote | None:
    session = row.get("session") or {}
    candidates = (
        ("last_trade", (row.get("last_trade") or {}).get("price")),
        ("last_minute", (row.get("last_minute") or {}).get("close")),
        ("session_close", session.get("close")),
        ("previous_close", session.get("previous_close")),
    )
    for source, price in candidates:
        if price:
            ts_ns = (row.get("last_trade") or {}).get("sip_timestamp")
            as_of_ms = ts_ns // 1_000_000 if ts_ns else int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
            return MassiveQuote(row["ticker"], float(price), session.get("previous_close"), as_of_ms, source)
    return None
```

Entitlement probing at startup (decides snapshot vs EOD mode once, then caches the decision):

```python
async def detect_mode(client: MassiveClient) -> str:
    try:
        await client.snapshot(["AAPL"])
        return "snapshot"          # Starter or above
    except NotEntitled:
        return "eod"               # Basic
```

Polling cadence recommendation:

| Mode | Plan | Interval | Why |
|---|---|---|---|
| `snapshot` | Advanced | 2 s | Real-time data; still one request per interval |
| `snapshot` | Starter / Developer | 15 s | Data is 15-min delayed; faster polling changes nothing |
| `eod` | Basic | 15 min | Data changes once a day; 1 call per 15 min is far under 5/min, and the walk-back may cost up to 10 calls |
| any | any | pause to 5 min when `market == closed` | Nothing moves; be kind to the quota |

If the official client is preferred anyway:

```python
from massive import RESTClient
client = RESTClient(api_key=os.environ["MASSIVE_API_KEY"])      # sync; wrap in asyncio.to_thread
snaps = list(client.list_universal_snapshots(type="stocks", ticker_any_of=["AAPL", "MSFT"], limit=250))
prev  = client.get_previous_close_agg("AAPL").close
bars  = client.get_grouped_daily_aggs("2026-10-14")
```

---

## 7. Things PLAN.md should be updated to say

- §11 stretch goal: "free tier 15s" is wrong. Free tier gets end-of-day closes only via grouped daily bars; prices are flat intraday. Snapshots require Starter ($29/mo) or above.
- §5: `MASSIVE_API_KEY` is also the env var name the official client reads, so no rename is needed.
- `/api/health` should report the mode (`"market_data": "massive:snapshot"` or `"massive:eod"`) so the UI can explain flat prices.

---

## Sources

- [Massive: Full Market Snapshot](https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot)
- [Massive: Unified Snapshot](https://massive.com/docs/rest/stocks/snapshots/unified-snapshot)
- [Massive: Single Ticker Snapshot](https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot)
- [Massive: Previous Day Bar](https://massive.com/docs/rest/stocks/aggregates/previous-day-bar)
- [Massive: Daily Market Summary (grouped daily)](https://massive.com/docs/rest/stocks/aggregates/daily-market-summary)
- [Massive: Market Status](https://massive.com/docs/rest/stocks/market-operations/market-status)
- [Massive: REST Quickstart (auth)](https://massive.com/docs/rest/quickstart)
- [Massive: Stocks REST overview (market hours, snapshot reset time)](https://massive.com/docs/rest/stocks/overview)
- [Massive: WebSocket aggregates per minute](https://massive.com/docs/websocket/stocks/aggregates-per-minute)
- [Massive: Pricing](https://massive.com/pricing)
- [Massive KB: one endpoint for latest trades, quotes and aggregates](https://massive.com/knowledge-base/article/does-massive-have-an-endpoint-that-returns-the-latest-trades-quotes-and-aggregates-in-one-request)
- [Massive KB: daily prices for all stocks](https://massive.com/knowledge-base/article/how-can-i-get-the-daily-prices-for-all-stocks-using-massives-market-data)
- [massive-com/client-python on GitHub](https://github.com/massive-com/client-python) and [massive on PyPI](https://pypi.org/project/massive/)
- [Polygon.io is now Massive](https://massive.com/blog/polygon-is-now-massive)

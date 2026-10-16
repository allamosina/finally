# data-testid contract (frontend-engineer <-> integration-tester)

`{T}` is the uppercase ticker, e.g. `watchlist-row-AAPL`.

| testid | element / requirement |
|---|---|
| `connection-status` | header dot. Attribute `data-status` = `connected` \| `reconnecting` \| `disconnected` |
| `header-total-value` | header total portfolio value, text like `$10,000.00` |
| `header-cash` | header cash balance, text like `$10,000.00` |
| `watchlist-panel` | watchlist container |
| `watchlist-row-{T}` | one row per watchlist ticker; clickable to select |
| `watchlist-price-{T}` | current price text (numeric) |
| `watchlist-change-{T}` | daily change %, text contains `%` |
| `watchlist-sparkline-{T}` | sparkline container |
| `watchlist-remove-{T}` | remove button in the row |
| `watchlist-add-input` / `watchlist-add-submit` | add-ticker input and button |
| `watchlist-error` | inline error, visible only when an add is rejected |
| `main-chart` | main chart container, attribute `data-ticker` = selected ticker |
| `trade-ticker` / `trade-quantity` | trade bar inputs |
| `trade-buy` / `trade-sell` | trade bar buttons |
| `trade-error` | inline API error text, rendered only when there is one |
| `positions-table` | table container (present even when empty) |
| `position-row-{T}` | one row per position (absent after full sell) |
| `position-qty-{T}` | quantity cell, text like `10` or `0.5` |
| `position-avg-cost-{T}` | avg cost cell, numeric text |
| `position-price-{T}` | current price cell (live from SSE) |
| `position-pnl-{T}` | unrealized P&L cell |
| `position-pnl-pct-{T}` | P&L % cell, text contains `%` |
| `heatmap` | treemap container |
| `heatmap-empty` | only when no positions; text exactly `No positions — buy something or ask the AI` |
| `heatmap-cell-{T}` | the SVG `rect` (or a `g` containing one) for a position; attribute `data-pnl-sign` = `profit` \| `loss` \| `flat`; the rect's computed `fill` is green-dominant for profit, red-dominant for loss |
| `pnl-chart` | P&L chart container, attribute `data-point-count` = number of points plotted (>= 1 always) |
| `chat-toggle` | button that opens/collapses the chat sidebar |
| `chat-input` / `chat-send` | message input and send button (input visible only when panel is open) |
| `chat-message` | each message bubble; attribute `data-role` = `user` \| `assistant` |
| `chat-loading` | loading indicator, in the DOM only while awaiting a response |
| `chat-chip` | one per action; attribute `data-status` = `executed` \| `failed`; text includes the ticker, and for failed chips the error text |

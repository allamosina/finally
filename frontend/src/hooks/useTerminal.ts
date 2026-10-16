"use client";

import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { liveApi, resolveApiMode, type Api, type ApiMode } from "@/lib/api";
import { mockApi, subscribeMockPrices } from "@/lib/mock";
import { revaluePortfolio } from "@/lib/pnl";
import { initialPriceState, latestPrices, priceReducer } from "@/lib/prices";
import { openPriceStream } from "@/lib/stream";
import type { ConnectionStatus, Portfolio, Side, TradeResponse, WatchlistItem } from "@/lib/types";

const EMPTY_PORTFOLIO: Portfolio = { cash_balance: 0, total_value: 0, unrealized_pnl: 0, positions: [] };

/**
 * All terminal state in one place. Server state (portfolio, watchlist) is fetched on load and
 * after mutations; between fetches the portfolio is revalued from SSE prices (PLAN §10).
 */
export function useTerminal() {
  const [mode, setMode] = useState<ApiMode | null>(null);
  const api: Api | null = mode === "mock" ? mockApi : mode === "live" ? liveApi : null;

  const [prices, dispatch] = useReducer(priceReducer, initialPriceState);
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  /** Bumped after every state-changing action so dependent panels (P&L chart) can refetch. */
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let alive = true;
    resolveApiMode().then((m) => alive && setMode(m));
    return () => {
      alive = false;
    };
  }, []);

  // Price stream.
  useEffect(() => {
    if (!mode) return;
    if (mode === "mock") {
      setStatus("connected");
      return subscribeMockPrices((event) => dispatch({ type: "prices", event }));
    }
    return openPriceStream("/api/stream/prices", (event) => dispatch({ type: "prices", event }), setStatus);
  }, [mode]);

  const refreshPortfolio = useCallback(async () => {
    if (!api) return;
    try {
      setPortfolio(await api.portfolio());
      setLoadError(null);
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, [api]);

  const refreshWatchlist = useCallback(async () => {
    if (!api) return;
    try {
      const list = await api.watchlist();
      setWatchlist(list);
      setSelected((cur) => cur ?? list[0]?.ticker ?? null);
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, [api]);

  useEffect(() => {
    refreshPortfolio();
    refreshWatchlist();
  }, [refreshPortfolio, refreshWatchlist]);

  // Main chart: select, then seed from history. The reducer drops stale seeds.
  useEffect(() => {
    if (!api || !selected) return;
    dispatch({ type: "chartSelect", ticker: selected });
    api
      .priceHistory(selected)
      .then((points) => dispatch({ type: "chartSeed", ticker: selected, points: Array.isArray(points) ? points : [] }))
      .catch(() => {
        /* Chart still fills from live ticks. */
      });
  }, [api, selected]);

  const trade = useCallback(
    async (ticker: string, quantity: number, side: Side): Promise<TradeResponse> => {
      if (!api) throw new Error("Still connecting");
      const res = await api.trade(ticker, quantity, side);
      setPortfolio(res.portfolio);
      setRevision((r) => r + 1);
      return res;
    },
    [api],
  );

  const addTicker = useCallback(
    async (ticker: string) => {
      if (!api) throw new Error("Still connecting");
      await api.addWatchlist(ticker);
      await refreshWatchlist();
      setSelected(ticker);
    },
    [api, refreshWatchlist],
  );

  const removeTicker = useCallback(
    async (ticker: string) => {
      if (!api) throw new Error("Still connecting");
      await api.removeWatchlist(ticker);
      setWatchlist((w) => w.filter((x) => x.ticker !== ticker));
      setSelected((cur) => (cur === ticker ? null : cur));
      await refreshWatchlist();
    },
    [api, refreshWatchlist],
  );

  /** Call after a chat response whose actions changed state. */
  const refreshAll = useCallback(async () => {
    await Promise.all([refreshPortfolio(), refreshWatchlist()]);
    setRevision((r) => r + 1);
  }, [refreshPortfolio, refreshWatchlist]);

  const live = useMemo(() => latestPrices(prices.quotes), [prices.quotes]);
  const view = useMemo(() => (portfolio ? revaluePortfolio(portfolio, live) : null), [portfolio, live]);

  return {
    mode,
    api,
    status,
    prices,
    live,
    portfolio: view ?? EMPTY_PORTFOLIO,
    portfolioLoaded: view !== null,
    watchlist,
    selected,
    select: setSelected,
    trade,
    addTicker,
    removeTicker,
    refreshAll,
    revision,
    loadError,
  };
}

export type TerminalState = ReturnType<typeof useTerminal>;

"use client";

import { useState } from "react";
import { useTerminal } from "@/hooks/useTerminal";
import { Header } from "./Header";
import { MainChart } from "./MainChart";
import { Empty, Slot } from "./Slot";
import { TradeBar } from "./TradeBar";
import { Watchlist } from "./Watchlist";

/**
 * Page layout. Desktop: watchlist | chart + trade + analytics | chat.
 * Below 1024px the columns stack and the page scrolls.
 */
export function Terminal() {
  const s = useTerminal();
  const [chatOpen, setChatOpen] = useState(true);
  const hasPositions = s.portfolio.positions.length > 0;

  return (
    <div className="flex min-h-screen flex-col lg:h-screen">
      <Header
        portfolio={s.portfolio}
        loaded={s.portfolioLoaded}
        status={s.status}
        lastTs={s.prices.lastTs}
        mode={s.mode}
      />
      {s.loadError && (
        <div role="alert" className="border-b border-down/40 bg-down/10 px-4 py-1.5 text-[12px] text-down">
          {s.loadError}
        </div>
      )}

      <main
        className={`grid min-h-0 flex-1 gap-1.5 p-1.5 lg:grid-cols-[minmax(250px,290px)_minmax(0,1fr)_auto]`}
      >
        <Watchlist
          items={s.watchlist}
          quotes={s.prices.quotes}
          sparks={s.prices.sparks}
          selected={s.selected}
          onSelect={s.select}
          onAdd={s.addTicker}
          onRemove={s.removeTicker}
        />

        <div className="grid min-h-0 gap-1.5 lg:grid-rows-[minmax(240px,1fr)_auto_minmax(170px,0.55fr)_minmax(150px,0.5fr)]">
          <div className="h-[340px] lg:h-auto lg:min-h-0 [&>section]:h-full">
            <MainChart ticker={s.selected} quote={s.selected ? s.prices.quotes[s.selected] : undefined} points={s.prices.chart} />
          </div>
          <TradeBar selected={s.selected} prices={s.live} cash={s.portfolio.cash_balance} onTrade={s.trade} />
          <div className="grid min-h-0 gap-1.5 md:grid-cols-2">
            <Slot title="Portfolio heatmap" testId="heatmap" className="min-h-[170px]">
              {hasPositions ? <Empty>Heatmap lands in the next build</Empty> : <Empty>No positions — buy something or ask the AI</Empty>}
            </Slot>
            <Slot title="Portfolio value" testId="pnl-chart" className="min-h-[170px]">
              <Empty>P&amp;L chart lands in the next build</Empty>
            </Slot>
          </div>
          <Slot title="Positions" testId="positions" className="min-h-[150px]">
            <Empty>{hasPositions ? "Positions table lands in the next build" : "No open positions"}</Empty>
          </Slot>
        </div>

        <aside
          className={`panel flex min-h-[320px] flex-col ${chatOpen ? "lg:w-[340px]" : "lg:w-[38px]"}`}
          aria-label="AI assistant"
          data-testid="chat-panel"
        >
          <div className="flex items-center justify-between border-b border-line px-2 py-2">
            {chatOpen && <h2 className="panel-title pl-1">FinAlly assistant</h2>}
            <button
              type="button"
              onClick={() => setChatOpen((o) => !o)}
              aria-expanded={chatOpen}
              aria-label={chatOpen ? "Collapse assistant" : "Expand assistant"}
              className="hidden h-6 w-6 items-center justify-center rounded-sm text-dim hover:bg-raised hover:text-ink lg:flex"
            >
              {chatOpen ? "›" : "‹"}
            </button>
          </div>
          {chatOpen && <Empty>Ask about your portfolio or place trades in plain language. The chat panel lands in the next build.</Empty>}
        </aside>
      </main>
    </div>
  );
}

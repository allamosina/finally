"use client";

import { useState } from "react";
import { useTerminal } from "@/hooks/useTerminal";
import { ChatPanel } from "./ChatPanel";
import { Header } from "./Header";
import { Heatmap } from "./Heatmap";
import { MainChart } from "./MainChart";
import { PnlChart } from "./PnlChart";
import { PositionsTable } from "./PositionsTable";
import { TradeBar } from "./TradeBar";
import { Watchlist } from "./Watchlist";

/**
 * Page layout. Desktop: watchlist | chart, order bar, heatmap + P&L, positions | assistant.
 * Below 1024px the columns stack and the page scrolls.
 */
export function Terminal() {
  const s = useTerminal();
  const [chatOpen, setChatOpen] = useState(true);

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

      <main className="grid min-h-0 flex-1 gap-1.5 p-1.5 lg:grid-cols-[minmax(250px,290px)_minmax(0,1fr)_auto]">
        <Watchlist
          items={s.watchlist}
          quotes={s.prices.quotes}
          sparks={s.prices.sparks}
          selected={s.selected}
          onSelect={s.select}
          onAdd={s.addTicker}
          onRemove={s.removeTicker}
        />

        <div className="grid min-h-0 gap-1.5 lg:grid-rows-[minmax(220px,1fr)_auto_minmax(180px,0.6fr)_minmax(150px,0.5fr)]">
          <div className="h-[340px] lg:h-auto lg:min-h-0 [&>section]:h-full">
            <MainChart ticker={s.selected} quote={s.selected ? s.prices.quotes[s.selected] : undefined} points={s.prices.chart} />
          </div>
          <TradeBar selected={s.selected} prices={s.live} cash={s.portfolio.cash_balance} onTrade={s.trade} />
          <div className="grid min-h-0 gap-1.5 md:grid-cols-2">
            <Heatmap positions={s.portfolio.positions} selected={s.selected} onSelect={s.select} />
            <PnlChart
              api={s.api}
              revision={s.revision}
              liveTotal={s.portfolio.total_value}
              liveTs={s.prices.lastTs}
              loaded={s.portfolioLoaded}
            />
          </div>
          <PositionsTable positions={s.portfolio.positions} selected={s.selected} onSelect={s.select} />
        </div>

        <ChatPanel api={s.api} open={chatOpen} onToggle={() => setChatOpen((o) => !o)} onActions={s.refreshAll} />
      </main>
    </div>
  );
}

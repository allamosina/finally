import { useEffect, useState } from "react";
import { formatMoney, formatQty, normalizeTicker, parseQuantity } from "@/lib/format";
import type { Side, TradeResponse } from "@/lib/types";

type Result = { tone: "ok" | "fail"; text: string } | null;

export function TradeBar({
  selected,
  prices,
  cash,
  onTrade,
}: {
  selected: string | null;
  prices: Record<string, number>;
  cash: number;
  onTrade: (ticker: string, quantity: number, side: Side) => Promise<TradeResponse>;
}) {
  const [ticker, setTicker] = useState(selected ?? "");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState<Side | null>(null);
  const [result, setResult] = useState<Result>(null);

  // Follow the watchlist selection.
  useEffect(() => {
    if (selected) {
      setTicker(selected);
      setResult(null);
    }
  }, [selected]);

  const t = normalizeTicker(ticker);
  const q = parseQuantity(qty);
  const price = t ? prices[t] : undefined;
  const estimate = q !== null && price !== undefined ? q * price : null;

  const submit = async (side: Side) => {
    if (!t) return setResult({ tone: "fail", text: "Enter a ticker of 1 to 5 letters" });
    if (q === null) return setResult({ tone: "fail", text: "Enter a quantity greater than 0" });
    setBusy(side);
    setResult(null);
    try {
      const { trade } = await onTrade(t, q, side);
      setResult({
        tone: "ok",
        text: `${trade.side === "buy" ? "Bought" : "Sold"} ${formatQty(trade.quantity)} ${trade.ticker} at ${formatMoney(trade.price)}`,
      });
      setQty("");
    } catch (e) {
      setResult({ tone: "fail", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel px-3 py-2" aria-label="Trade" data-testid="trade-bar">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit("buy");
        }}
      >
        <h2 className="panel-title mr-1">Market order</h2>
        <label className="flex items-center gap-1.5">
          <span className="text-[12px] text-faint">Ticker</span>
          <input
            data-testid="trade-ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            maxLength={8}
            spellCheck={false}
            autoComplete="off"
            className="num w-[84px] rounded-sm border border-line bg-bg px-2 py-1 text-ink focus:border-blue focus:outline-none"
          />
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-[12px] text-faint">Quantity</span>
          <input
            data-testid="trade-quantity"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            inputMode="decimal"
            placeholder="0"
            autoComplete="off"
            className="num w-[96px] rounded-sm border border-line bg-bg px-2 py-1 text-right text-ink focus:border-blue focus:outline-none"
          />
        </label>
        <span className="num min-w-[150px] text-[12px] text-dim" data-testid="trade-estimate">
          {estimate !== null ? `≈ ${formatMoney(estimate)}` : ""}
          {estimate !== null && estimate > cash + 1e-6 ? <span className="text-down"> over cash</span> : null}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            type="submit"
            data-testid="trade-buy"
            disabled={busy !== null}
            className="rounded-sm bg-purple px-4 py-1 font-semibold text-white hover:bg-purple-hi disabled:opacity-50"
          >
            {busy === "buy" ? "Buying" : "Buy"}
          </button>
          <button
            type="button"
            data-testid="trade-sell"
            disabled={busy !== null}
            onClick={() => submit("sell")}
            className="rounded-sm border border-purple px-4 py-1 font-semibold text-ink hover:bg-purple/25 disabled:opacity-50"
          >
            {busy === "sell" ? "Selling" : "Sell"}
          </button>
        </div>
      </form>
      {result && (
        <p
          role={result.tone === "fail" ? "alert" : "status"}
          data-testid={result.tone === "fail" ? "trade-error" : "trade-result"}
          className={`mt-1.5 text-[12px] ${result.tone === "fail" ? "text-down" : "text-up"}`}
        >
          {result.text}
        </p>
      )}
    </section>
  );
}

import { formatMoney, formatPct, formatPrice, formatQty, formatSignedMoney, toneOf } from "@/lib/format";
import type { Position } from "@/lib/types";

const TONE = { up: "text-up", down: "text-down", flat: "text-dim" } as const;

export function PositionsTable({
  positions,
  selected,
  onSelect,
}: {
  positions: Position[];
  selected: string | null;
  onSelect: (t: string) => void;
}) {
  const rows = [...positions].sort((a, b) => b.market_value - a.market_value);
  return (
    <section className="panel flex min-h-[150px] flex-col" aria-label="Positions" data-testid="positions-table">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 className="panel-title">Positions</h2>
        <span className="num text-[11px] text-faint">{positions.length}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-right">
          <thead className="sticky top-0 bg-panel text-[11px] text-faint">
            <tr className="border-b border-line">
              <th scope="col" className="px-3 py-1.5 text-left font-medium">Ticker</th>
              <th scope="col" className="px-3 py-1.5 font-medium">Quantity</th>
              <th scope="col" className="px-3 py-1.5 font-medium">Avg cost</th>
              <th scope="col" className="px-3 py-1.5 font-medium">Price</th>
              <th scope="col" className="px-3 py-1.5 font-medium">Market value</th>
              <th scope="col" className="px-3 py-1.5 font-medium">Unrealized P&amp;L</th>
              <th scope="col" className="px-3 py-1.5 font-medium">P&amp;L %</th>
            </tr>
          </thead>
          <tbody className="num">
            {rows.map((p) => {
              const tone = TONE[toneOf(p.unrealized_pnl)];
              const t = p.ticker;
              return (
                <tr
                  key={t}
                  data-testid={`position-row-${t}`}
                  onClick={() => onSelect(t)}
                  className={`cursor-pointer border-b border-line/60 ${t === selected ? "bg-raised" : "hover:bg-raised/60"}`}
                >
                  <th scope="row" className="px-3 py-1 text-left font-sans font-semibold text-ink">{t}</th>
                  <td className="px-3 py-1" data-testid={`position-qty-${t}`}>{formatQty(p.quantity)}</td>
                  <td className="px-3 py-1 text-dim" data-testid={`position-avg-cost-${t}`}>{formatPrice(p.avg_cost)}</td>
                  <td className="px-3 py-1" data-testid={`position-price-${t}`}>{formatPrice(p.current_price)}</td>
                  <td className="px-3 py-1 text-dim">{formatMoney(p.market_value)}</td>
                  <td className={`px-3 py-1 ${tone}`} data-testid={`position-pnl-${t}`}>{formatSignedMoney(p.unrealized_pnl)}</td>
                  <td className={`px-3 py-1 ${tone}`} data-testid={`position-pnl-pct-${t}`}>{formatPct(p.pnl_pct)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="px-4 py-6 text-center text-dim">No open positions. Use the order bar or ask the assistant to buy.</p>
        )}
      </div>
    </section>
  );
}

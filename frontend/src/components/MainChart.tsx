import { useMemo } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatClock, formatPct, formatPrice, toneOf } from "@/lib/format";
import type { PricePoint, Quote } from "@/lib/types";

const TONE = { up: "text-up", down: "text-down", flat: "text-dim" } as const;

export function MainChart({ ticker, quote, points }: { ticker: string | null; quote: Quote | undefined; points: PricePoint[] }) {
  const data = useMemo(() => points.map((p) => ({ t: Date.parse(p.ts), price: p.price })), [points]);
  const tone = toneOf(quote?.change_pct);
  const stroke = tone === "down" ? "var(--color-down)" : "var(--color-blue)";
  const change = quote ? quote.price - quote.session_open : null;

  return (
    <section className="panel flex flex-col" aria-label="Price chart" data-testid="main-chart">
      <div className="flex flex-wrap items-end gap-x-5 gap-y-1 border-b border-line px-4 pb-2 pt-3">
        <div className="flex flex-col">
          <span className="text-[12px] text-dim">Selected</span>
          <h2 className="text-[22px] font-semibold leading-none tracking-tight text-ink" data-testid="chart-ticker">
            {ticker ?? "—"}
          </h2>
        </div>
        <span className="num border-b-2 border-accent pb-0.5 text-[30px] leading-none text-accent" data-testid="chart-price">
          {formatPrice(quote?.price)}
        </span>
        <div className={`num flex gap-3 pb-0.5 ${TONE[tone]}`}>
          <span>{change === null ? "—" : (change > 0 ? "+" : "") + formatPrice(change)}</span>
          <span>{formatPct(quote?.change_pct)}</span>
        </div>
        <span className="num ml-auto pb-0.5 text-[12px] text-faint">
          Session open {formatPrice(quote?.session_open)}
        </span>
      </div>
      <div className="min-h-0 flex-1 px-1 pb-1 pt-2">
        {data.length < 2 ? (
          <div className="flex h-full items-center justify-center text-dim">
            {ticker ? "Waiting for price ticks" : "Select a ticker from the watchlist"}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--color-line)" strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => formatClock(new Date(t).toISOString())}
                stroke="var(--color-faint)"
                tick={{ fontSize: 11, fontFamily: "var(--font-mono)" }}
                tickLine={false}
                axisLine={{ stroke: "var(--color-line)" }}
                minTickGap={60}
              />
              <YAxis
                orientation="right"
                domain={[(min: number) => min - Math.max(0.01, min * 0.0005), (max: number) => max + Math.max(0.01, max * 0.0005)]}
                tickFormatter={(v: number) => formatPrice(v)}
                stroke="var(--color-faint)"
                tick={{ fontSize: 11, fontFamily: "var(--font-mono)" }}
                tickLine={false}
                axisLine={false}
                width={64}
              />
              {quote && (
                <ReferenceLine y={quote.session_open} stroke="var(--color-faint)" strokeDasharray="4 4" ifOverflow="extendDomain" />
              )}
              <Tooltip
                isAnimationActive={false}
                cursor={{ stroke: "var(--color-line-strong)" }}
                contentStyle={{
                  background: "var(--color-raised)",
                  border: "1px solid var(--color-line-strong)",
                  borderRadius: 3,
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                }}
                labelStyle={{ color: "var(--color-dim)" }}
                itemStyle={{ color: "var(--color-ink)" }}
                labelFormatter={(t) => formatClock(new Date(Number(t)).toISOString())}
                formatter={(v) => [formatPrice(Number(v)), "Price"]}
              />
              <Area
                type="linear"
                dataKey="price"
                stroke={stroke}
                strokeWidth={1.5}
                fill="url(#chartFill)"
                isAnimationActive={false}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

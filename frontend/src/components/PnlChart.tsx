import { useEffect, useMemo, useState } from "react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Api } from "@/lib/api";
import { formatClock, formatMoney, formatSignedMoney, toneOf } from "@/lib/format";
import type { Snapshot } from "@/lib/types";

/** Backend records a snapshot every 30 s; refetch on the same cadence and after every trade. */
const REFRESH_MS = 30_000;
const TONE = { up: "text-up", down: "text-down", flat: "text-dim" } as const;

export function PnlChart({
  api,
  revision,
  liveTotal,
  liveTs,
  loaded,
}: {
  api: Api | null;
  revision: number;
  liveTotal: number;
  liveTs: string | null;
  loaded: boolean;
}) {
  const [snaps, setSnaps] = useState<Snapshot[]>([]);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    const load = () =>
      api
        .portfolioHistory({ limit: 500 })
        .then((s) => alive && Array.isArray(s) && setSnaps(s))
        .catch(() => {});
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [api, revision]);

  // Server snapshots plus one trailing live point so the line moves between snapshots.
  const data = useMemo(() => {
    const pts = snaps.map((s) => ({ t: Date.parse(s.recorded_at), v: s.total_value }));
    if (loaded && liveTs) {
      const t = Date.parse(liveTs);
      if (!pts.length || t > pts[pts.length - 1].t) pts.push({ t, v: liveTotal });
    }
    return pts;
  }, [snaps, loaded, liveTotal, liveTs]);

  const base = snaps[0]?.total_value ?? null;
  const change = base !== null && loaded ? liveTotal - base : null;
  const tone = toneOf(change);
  const stroke = tone === "down" ? "var(--color-down)" : tone === "up" ? "var(--color-up)" : "var(--color-blue)";

  return (
    <section
      className="panel flex min-h-[170px] flex-col"
      aria-label="Portfolio value"
      data-testid="pnl-chart"
      data-point-count={data.length}
    >
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 className="panel-title">Portfolio value</h2>
        <span className={`num text-[12px] ${TONE[tone]}`} title="Change since the first snapshot">
          {change === null ? "" : formatSignedMoney(change)}
        </span>
      </div>
      <div className="min-h-0 flex-1 px-1 pb-1 pt-2">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-dim">Waiting for the first snapshot</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%" minHeight={110}>
            <LineChart data={data.length === 1 ? [data[0], { ...data[0], t: data[0].t + 1 }] : data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(t: number) => formatClock(new Date(t).toISOString()).slice(0, 5)}
                stroke="var(--color-faint)"
                tick={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
                tickLine={false}
                axisLine={{ stroke: "var(--color-line)" }}
                minTickGap={50}
              />
              <YAxis
                orientation="right"
                domain={[(min: number) => Math.floor(min - Math.max(1, min * 0.001)), (max: number) => Math.ceil(max + Math.max(1, max * 0.001))]}
                tickFormatter={(v: number) => `$${Math.round(v).toLocaleString("en-US")}`}
                stroke="var(--color-faint)"
                tick={{ fontSize: 10, fontFamily: "var(--font-mono)" }}
                tickLine={false}
                axisLine={false}
                width={66}
              />
              {base !== null && <ReferenceLine y={base} stroke="var(--color-faint)" strokeDasharray="4 4" />}
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
                formatter={(v) => [formatMoney(Number(v)), "Value"]}
              />
              <Line type="linear" dataKey="v" stroke={stroke} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

import { memo } from "react";
import { Line, LineChart, YAxis } from "recharts";

/** Tiny price line accumulated since page load. Colored by direction over the window. */
export const Sparkline = memo(function Sparkline({
  points,
  width = 76,
  height = 24,
}: {
  points: number[] | undefined;
  width?: number;
  height?: number;
}) {
  if (!points || points.length < 2) {
    return <div style={{ width, height }} className="flex items-center"><div className="h-px w-full bg-line" /></div>;
  }
  const up = points[points.length - 1] >= points[0];
  const data = points.map((v, i) => ({ i, v }));
  return (
    <LineChart width={width} height={height} data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
      <YAxis hide domain={["dataMin", "dataMax"]} />
      <Line
        type="linear"
        dataKey="v"
        stroke={up ? "var(--color-up)" : "var(--color-down)"}
        strokeWidth={1.25}
        dot={false}
        isAnimationActive={false}
      />
    </LineChart>
  );
});

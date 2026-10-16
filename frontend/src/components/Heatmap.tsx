import { useMemo } from "react";
import { ResponsiveContainer, Treemap } from "recharts";
import { formatPct } from "@/lib/format";
import { heatCells, type HeatCell } from "@/lib/heatmap";
import type { Position } from "@/lib/types";

export const HEATMAP_EMPTY = "No positions — buy something or ask the AI";

interface NodeProps extends Partial<HeatCell> {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  depth?: number;
}

function Cell(props: NodeProps & { selected: string | null; onSelect: (t: string) => void }) {
  const { x = 0, y = 0, width = 0, height = 0, depth, name, fill, sign, pnlPct = 0, selected, onSelect } = props;
  // Recharts also renders the root node (depth 0); only leaves are positions.
  if (depth !== 1 || !name) return <g />;
  const showLabel = width > 44 && height > 26;
  const showPct = width > 56 && height > 42;
  return (
    <g
      data-testid={`heatmap-cell-${name}`}
      data-pnl-sign={sign}
      onClick={() => onSelect(name)}
      style={{ cursor: "pointer" }}
    >
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={fill}
        stroke={name === selected ? "#ecad0a" : "#0d1117"}
        strokeWidth={name === selected ? 2 : 1.5}
      />
      <title>{`${name} ${formatPct(pnlPct)}`}</title>
      {showLabel && (
        <text x={x + 7} y={y + 17} fill="#eef2f6" fontSize={13} fontWeight={600} fontFamily="var(--font-sans)">
          {name}
        </text>
      )}
      {showPct && (
        <text x={x + 7} y={y + 33} fill="#eef2f6" fillOpacity={0.85} fontSize={11} fontFamily="var(--font-mono)">
          {formatPct(pnlPct)}
        </text>
      )}
    </g>
  );
}

export function Heatmap({
  positions,
  selected,
  onSelect,
}: {
  positions: Position[];
  selected: string | null;
  onSelect: (t: string) => void;
}) {
  const cells = useMemo(() => heatCells(positions), [positions]);
  return (
    <section className="panel flex min-h-[170px] flex-col" aria-label="Portfolio heatmap" data-testid="heatmap">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 className="panel-title">Portfolio heatmap</h2>
        <span className="text-[11px] text-faint">Size by weight, colour by P&amp;L</span>
      </div>
      <div className="min-h-0 flex-1 p-1">
        {cells.length === 0 ? (
          <div className="flex h-full items-center justify-center px-4 text-center text-dim">
            <span data-testid="heatmap-empty">{HEATMAP_EMPTY}</span>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%" minHeight={120}>
            <Treemap
              data={cells as unknown as Record<string, unknown>[]}
              dataKey="size"
              nameKey="name"
              aspectRatio={1.6}
              isAnimationActive={false}
              content={<Cell selected={selected} onSelect={onSelect} />}
            />
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

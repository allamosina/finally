import { formatClock, formatMoney, formatSignedMoney, toneOf } from "@/lib/format";
import type { ApiMode } from "@/lib/api";
import type { ConnectionStatus, Portfolio } from "@/lib/types";

const STATUS: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: "bg-up", label: "Live" },
  reconnecting: { color: "bg-accent", label: "Reconnecting" },
  disconnected: { color: "bg-down", label: "Disconnected" },
};

const TONE = { up: "text-up", down: "text-down", flat: "text-dim" } as const;

export function Header({
  portfolio,
  loaded,
  status,
  lastTs,
  mode,
}: {
  portfolio: Portfolio;
  loaded: boolean;
  status: ConnectionStatus;
  lastTs: string | null;
  mode: ApiMode | null;
}) {
  const s = STATUS[status];
  return (
    <header className="flex items-stretch gap-6 border-b border-line bg-panel px-4">
      <div className="flex items-center gap-2 py-2 pr-2">
        <span className="h-5 w-1 rounded-sm bg-accent" aria-hidden />
        <span className="text-[17px] font-semibold tracking-tight text-ink">
          Fin<span className="text-accent">Ally</span>
        </span>
      </div>

      <dl className="flex items-center gap-6">
        <Figure label="Portfolio value" testId="header-total-value">
          <span className="text-[18px] text-ink">{loaded ? formatMoney(portfolio.total_value) : "—"}</span>
        </Figure>
        <Figure label="Cash" testId="header-cash">
          <span className="text-ink">{loaded ? formatMoney(portfolio.cash_balance) : "—"}</span>
        </Figure>
        <Figure label="Unrealized P&L" testId="header-pnl">
          <span className={TONE[toneOf(portfolio.unrealized_pnl)]}>
            {loaded ? formatSignedMoney(portfolio.unrealized_pnl) : "—"}
          </span>
        </Figure>
      </dl>

      <div className="ml-auto flex items-center gap-4 text-dim">
        {mode === "mock" && (
          <span
            className="rounded-sm border border-accent/40 px-1.5 py-0.5 text-[11px] text-accent"
            title="No backend detected: prices and trades are simulated in the browser"
          >
            Offline demo data
          </span>
        )}
        <span className="num hidden text-[12px] sm:inline" title="Last price update">
          {formatClock(lastTs)}
        </span>
        <span
          className="flex items-center gap-1.5 text-[12px]"
          data-testid="connection-status"
          data-status={status}
          role="status"
          aria-label={`Price stream: ${s.label}`}
        >
          <span className={`h-2 w-2 rounded-full ${s.color} ${status === "reconnecting" ? "dot-pulse" : ""}`} />
          {s.label}
        </span>
      </div>
    </header>
  );
}

function Figure({ label, testId, children }: { label: string; testId: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col justify-center leading-tight">
      <dt className="text-[11px] text-faint">{label}</dt>
      <dd className="num" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

import { memo, useEffect, useRef, useState } from "react";
import { formatPct, formatPrice, normalizeTicker, toneOf } from "@/lib/format";
import type { Quote, WatchlistItem } from "@/lib/types";
import { Sparkline } from "./Sparkline";

const TONE = { up: "text-up", down: "text-down", flat: "text-dim" } as const;

/** Returns a flash class for ~500 ms whenever the price changes. */
function useFlash(price: number | undefined, direction: Quote["direction"] | undefined) {
  const [cls, setCls] = useState("");
  const prev = useRef(price);
  const parity = useRef(0);
  useEffect(() => {
    if (price === undefined || prev.current === undefined || price === prev.current) {
      prev.current = price;
      return;
    }
    const dir = direction && direction !== "flat" ? direction : price > prev.current ? "up" : "down";
    prev.current = price;
    parity.current ^= 1;
    setCls(`flash-${dir}-${parity.current}`);
    const t = setTimeout(() => setCls(""), 500);
    return () => clearTimeout(t);
  }, [price, direction]);
  return cls;
}

const Row = memo(function Row({
  ticker,
  quote,
  spark,
  selected,
  onSelect,
  onRemove,
}: {
  ticker: string;
  quote: Quote | undefined;
  spark: number[] | undefined;
  selected: boolean;
  onSelect: (t: string) => void;
  onRemove: (t: string) => void;
}) {
  const flash = useFlash(quote?.price, quote?.direction);
  const tone = TONE[toneOf(quote?.change_pct)];
  return (
    <li
      data-testid={`watchlist-row-${ticker}`}
      className={`group relative grid cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-line/60 py-1.5 pl-3 pr-2 ${
        selected ? "bg-raised" : "hover:bg-raised/60"
      }`}
      onClick={() => onSelect(ticker)}
    >
      {selected && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" aria-hidden />}
      <button
        type="button"
        className="text-left font-semibold text-ink focus-visible:outline-accent"
        aria-pressed={selected}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(ticker);
        }}
      >
        {ticker}
      </button>
      <Sparkline points={spark} />
      <div className="flex w-[92px] flex-col items-end">
        <span data-testid={`price-${ticker}`} className={`num rounded-sm px-1 text-ink ${flash}`}>
          {formatPrice(quote?.price)}
        </span>
        <span className={`num px-1 text-[11px] ${tone}`}>{formatPct(quote?.change_pct)}</span>
      </div>
      <button
        type="button"
        aria-label={`Remove ${ticker} from watchlist`}
        title={`Remove ${ticker}`}
        className="absolute right-1 top-1 hidden h-4 w-4 items-center justify-center rounded-sm text-[12px] leading-none text-faint hover:bg-line hover:text-ink focus-visible:flex group-hover:flex"
        onClick={(e) => {
          e.stopPropagation();
          onRemove(ticker);
        }}
      >
        ×
      </button>
    </li>
  );
});

export function Watchlist({
  items,
  quotes,
  sparks,
  selected,
  onSelect,
  onAdd,
  onRemove,
}: {
  items: WatchlistItem[];
  quotes: Record<string, Quote>;
  sparks: Record<string, number[]>;
  selected: string | null;
  onSelect: (t: string) => void;
  onAdd: (t: string) => Promise<void>;
  onRemove: (t: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = normalizeTicker(draft);
    if (!t) {
      setError("Use 1 to 5 letters, like PYPL");
      return;
    }
    if (items.some((i) => i.ticker === t)) {
      setError(`${t} is already on the watchlist`);
      return;
    }
    setBusy(true);
    try {
      await onAdd(t);
      setDraft("");
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (t: string) => {
    try {
      await onRemove(t);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section className="panel flex flex-col" aria-label="Watchlist" data-testid="watchlist">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <h2 className="panel-title">Watchlist</h2>
        <span className="num text-[11px] text-faint">{items.length}</span>
      </div>
      <form onSubmit={submit} className="border-b border-line px-2 py-2">
        <div className="flex gap-1.5">
          <input
            data-testid="watchlist-add-input"
            aria-label="Ticker to add"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value.toUpperCase());
              setError(null);
            }}
            placeholder="Add ticker"
            maxLength={8}
            spellCheck={false}
            autoComplete="off"
            className="num min-w-0 flex-1 rounded-sm border border-line bg-bg px-2 py-1 text-ink focus:border-blue focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            data-testid="watchlist-add-button"
            className="rounded-sm border border-line-strong px-2.5 text-dim hover:border-blue hover:text-ink disabled:opacity-40"
          >
            Add
          </button>
        </div>
        {error && (
          <p role="alert" data-testid="watchlist-error" className="mt-1.5 text-[12px] text-down">
            {error}
          </p>
        )}
      </form>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {items.map((w) => (
          <Row
            key={w.ticker}
            ticker={w.ticker}
            quote={quotes[w.ticker]}
            spark={sparks[w.ticker]}
            selected={w.ticker === selected}
            onSelect={onSelect}
            onRemove={remove}
          />
        ))}
        {items.length === 0 && (
          <li className="px-3 py-6 text-center text-dim">Your watchlist is empty. Add a ticker above.</li>
        )}
      </ul>
    </section>
  );
}

import { useEffect, useRef, useState } from "react";
import type { Api } from "@/lib/api";
import { actionChips } from "@/lib/chips";
import { formatClock } from "@/lib/format";
import type { ChatActions, ChatMessage } from "@/lib/types";

const SUGGESTIONS = ["How is my portfolio doing?", "Buy 5 AAPL", "Add PYPL to my watchlist"];

function Chips({ actions }: { actions: ChatActions | null }) {
  const chips = actionChips(actions);
  if (!chips.length) return null;
  return (
    <ul className="mt-1.5 flex flex-col gap-1">
      {chips.map((c) => (
        <li
          key={c.key}
          data-testid="chat-chip"
          data-status={c.tone === "ok" ? "executed" : "failed"}
          className={`rounded-sm border px-2 py-1 text-[12px] ${
            c.tone === "ok" ? "border-up/40 bg-up/10 text-up" : "border-down/40 bg-down/10 text-down"
          }`}
        >
          <span className="font-semibold">{c.tone === "ok" ? "✓ " : "✕ "}{c.label}</span>
          {c.detail && <span className="block text-[11px] opacity-90">{c.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

export function ChatPanel({
  api,
  open,
  onToggle,
  onActions,
}: {
  api: Api | null;
  open: boolean;
  onToggle: () => void;
  onActions: () => Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!api) return;
    api
      .chatHistory(50)
      .then((h) => Array.isArray(h) && setMessages(h))
      .catch(() => {});
  }, [api]);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, pending, open]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || pending || !api) return;
    setDraft("");
    setError(null);
    setPending(true);
    const now = new Date().toISOString();
    setMessages((m) => [...m, { id: `local-${now}`, role: "user", content: message, actions: null, created_at: now }]);
    try {
      const res = await api.chat(message);
      setMessages((m) => [
        ...m,
        { id: `reply-${now}`, role: "assistant", content: res.message, actions: res.actions, created_at: new Date().toISOString() },
      ]);
      // PLAN §10: refetch the portfolio after every chat response.
      await onActions();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <aside
      className={`panel flex min-h-[360px] flex-col lg:min-h-0 ${open ? "lg:w-[340px]" : "lg:w-[40px]"}`}
      aria-label="AI assistant"
      data-testid="chat-panel"
    >
      <div className="flex items-center justify-between border-b border-line px-2 py-2">
        {open && <h2 className="panel-title pl-1">FinAlly assistant</h2>}
        <button
          type="button"
          data-testid="chat-toggle"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? "Collapse assistant" : "Open assistant"}
          title={open ? "Collapse assistant" : "Open assistant"}
          className="flex h-6 w-6 items-center justify-center rounded-sm text-dim hover:bg-raised hover:text-ink"
        >
          {open ? "›" : "‹"}
        </button>
      </div>

      {open && (
        <>
          <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3" aria-live="polite">
            {messages.length === 0 && !pending && (
              <div className="space-y-2 text-dim">
                <p>Ask about your positions, risk and P&amp;L, or tell me to trade or change the watchlist.</p>
                <div className="flex flex-wrap gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => send(s)}
                      className="rounded-sm border border-line-strong px-2 py-0.5 text-[12px] text-dim hover:border-blue hover:text-ink"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <div
                key={m.id}
                data-testid="chat-message"
                data-role={m.role}
                className={m.role === "user" ? "ml-8 flex flex-col items-end" : "mr-2 flex flex-col"}
              >
                <div
                  className={`whitespace-pre-wrap rounded-sm px-2.5 py-1.5 ${
                    m.role === "user" ? "bg-raised text-ink" : "border-l-2 border-blue bg-transparent pl-2.5 text-ink"
                  }`}
                >
                  {m.content}
                </div>
                {m.role === "assistant" && <Chips actions={m.actions} />}
                <span className="num mt-0.5 text-[10px] text-faint">{formatClock(m.created_at)}</span>
              </div>
            ))}
            {pending && (
              <div data-testid="chat-loading" className="flex items-center gap-2 text-dim" role="status">
                <span className="flex gap-1" aria-hidden>
                  <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-blue" />
                  <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-blue [animation-delay:200ms]" />
                  <span className="dot-pulse h-1.5 w-1.5 rounded-full bg-blue [animation-delay:400ms]" />
                </span>
                FinAlly is working on it
              </div>
            )}
            {error && (
              <p role="alert" data-testid="chat-error" className="rounded-sm border border-down/40 bg-down/10 px-2 py-1 text-[12px] text-down">
                {error}
              </p>
            )}
          </div>
          <form
            className="flex gap-1.5 border-t border-line p-2"
            onSubmit={(e) => {
              e.preventDefault();
              send(draft);
            }}
          >
            <input
              data-testid="chat-input"
              aria-label="Message the assistant"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask FinAlly"
              autoComplete="off"
              className="min-w-0 flex-1 rounded-sm border border-line bg-bg px-2 py-1.5 text-ink focus:border-blue focus:outline-none"
            />
            <button
              type="submit"
              data-testid="chat-send"
              disabled={pending || !draft.trim() || !api}
              className="rounded-sm bg-purple px-3 font-semibold text-white hover:bg-purple-hi disabled:opacity-50"
            >
              Send
            </button>
          </form>
        </>
      )}
    </aside>
  );
}

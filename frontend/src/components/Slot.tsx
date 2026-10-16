/** A titled panel. Wave 2 panels (positions, heatmap, P&L, chat) render inside these. */
export function Slot({
  title,
  testId,
  className = "",
  children,
}: {
  title: string;
  testId?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`panel flex flex-col ${className}`} aria-label={title} data-testid={testId}>
      <div className="flex items-center border-b border-line px-3 py-2">
        <h2 className="panel-title">{title}</h2>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="flex h-full min-h-16 items-center justify-center px-4 text-center text-dim">{children}</div>;
}

import { Calendar } from "lucide-react";
import { MaximizeButton } from "@/components/shell/MaximizeButton";
import type { NewsBlock, NewsTodayEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Economic calendar widget: next high-impact release, symbols it affects,
 * and any symbols currently news-blocked. Deliberately uses warning/muted
 * tokens (NOT profit/loss tones) — this is calendar risk, not P&L. */
export function NewsPanel({
  data,
  className,
  onMaximize,
  hideHeader,
}: {
  data?: NewsBlock;
  className?: string;
  onMaximize?: () => void;
  /** Suppresses this panel's own "Economic Calendar" header. Used ONLY by the
   *  maximized-dialog call site, which already renders a `DialogTitle` with
   *  the same text — without this, the dialog shows two identical headings.
   *  The collapsed card always passes this as falsy/omitted, so its header
   *  (including the maximize button and status badge) is unaffected. */
  hideHeader?: boolean;
}) {
  if (!data || data.status === "unavailable") {
    return (
      <div
        data-testid="news-panel"
        className={cn(
          "flex flex-col gap-2 rounded-lg border border-border bg-surface-1 p-4",
          className
        )}
      >
        {!hideHeader && <Header status={data?.status} onMaximize={onMaximize} />}
        <div
          data-testid="news-panel-empty"
          className="flex flex-col items-center justify-center gap-1 rounded-md border border-border bg-surface-2 px-3 py-6 text-center"
        >
          <span className="text-sm text-muted-foreground">Economic calendar unavailable</span>
          <span className="max-w-[24ch] text-xs text-muted-foreground/70">
            No news feed is connected yet — populated once the calendar source is live.
          </span>
        </div>
      </div>
    );
  }

  const next = data.next ?? null;
  const affects = next?.affects ?? [];
  const blocked = Object.entries(data.blocked_symbols ?? {});
  const today = data.today ?? [];

  return (
    <div
      data-testid="news-panel"
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-4",
        className
      )}
    >
      {!hideHeader && (
        <Header status={data.status} cacheAgeMin={data.cache_age_min} onMaximize={onMaximize} />
      )}

      {data.status === "stale" && (
        <div
          data-testid="news-panel-stale"
          className="rounded-md border border-warning/40 bg-warning/10 px-3 py-1.5 text-xs text-warning"
        >
          Calendar data is stale{data.cache_age_min != null ? ` (${data.cache_age_min}m old)` : ""}.
        </div>
      )}

      {next ? (
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium text-foreground">{next.title}</span>
            <span className="font-mono tabnum text-xs text-warning">in {next.in_min}m</span>
          </div>
          <div className="text-xs text-muted-foreground">
            {next.currency} · {next.importance}
            {next.forecast != null && <> · forecast {next.forecast}</>}
            {next.previous != null && <> · previous {next.previous}</>}
          </div>
          {affects.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {affects.map((sym) => (
                <span
                  key={sym}
                  className="rounded-full border border-border bg-surface-2 px-2 py-0.5 font-mono text-xs text-foreground"
                >
                  {sym}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <span className="text-xs text-muted-foreground">No upcoming high-impact events.</span>
      )}

      {today.length > 0 && (
        <div
          data-testid="news-today-strip"
          className="flex flex-col gap-1 border-t border-border pt-2"
        >
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Today
          </span>
          {today.map((event, i) => (
            <TodayRow key={`${event.when_utc}-${i}`} event={event} />
          ))}
        </div>
      )}

      {blocked.length > 0 && (
        <div className="flex flex-col gap-1 border-t border-border pt-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Blocked
          </span>
          {blocked.map(([symbol, reason]) => (
            <div key={symbol} className="text-xs text-muted-foreground">
              <span className="font-mono text-foreground">{symbol}</span> — {reason}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const todayTimeFormatter = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

function formatTodayTime(whenUtc: string): string {
  const parsed = new Date(whenUtc);
  if (Number.isNaN(parsed.getTime())) return "--:--";
  return `${todayTimeFormatter.format(parsed)}Z`;
}

/** One row of the "today" strip: time + currency + title. A title with a
 * dashboard `url` (spec §2.1) opens in a new tab; without one it's plain
 * text -- never an anchor with an empty/undefined href. */
function TodayRow({ event }: { event: NewsTodayEvent }) {
  return (
    <div className="flex items-baseline gap-2 text-xs text-muted-foreground">
      <span className="font-mono tabnum">{formatTodayTime(event.when_utc)}</span>
      <span className="font-mono text-foreground">{event.currency}</span>
      {event.url ? (
        <a
          href={event.url}
          target="_blank"
          rel="noopener noreferrer"
          className="truncate text-foreground underline-offset-2 hover:underline"
        >
          {event.title}
        </a>
      ) : (
        <span className="truncate text-foreground">{event.title}</span>
      )}
    </div>
  );
}

function Header({
  status,
  cacheAgeMin,
  onMaximize,
}: {
  status?: NewsBlock["status"];
  cacheAgeMin?: number | null;
  onMaximize?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h3 className="flex min-w-0 items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <Calendar className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate" title="Economic Calendar">
          Economic Calendar
        </span>
      </h3>
      <div className="flex items-center gap-1.5">
        {status === "degraded" ? (
          <span className="rounded-full border border-warning/40 bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning">
            degraded
          </span>
        ) : status === "ok" && cacheAgeMin != null ? (
          <span className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted-foreground">
            {cacheAgeMin}m old
          </span>
        ) : null}
        {onMaximize && <MaximizeButton title="Economic Calendar" onClick={onMaximize} />}
      </div>
    </div>
  );
}

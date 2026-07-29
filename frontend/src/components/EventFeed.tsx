import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import type { FeedEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function formatTs(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleTimeString();
  } catch {
    return String(ts);
  }
}

function detailText(rest: Record<string, unknown>, skip: string[] = []): string {
  return Object.entries(rest)
    .filter(([k]) => !skip.includes(k))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" ");
}

/**
 * Append-only event feed (design-system §6): IntentBlocked rows render the
 * `rule` (opposition/ttl-dedup/cap) as a violet chip + detail. Newest-last,
 * auto-scrolls to bottom on new events unless the user is hovering (reading
 * back) or prefers-reduced-motion (instant jump instead of smooth scroll).
 */
export function EventFeed({ events }: { events: FeedEvent[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hovering, setHovering] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || hovering || typeof el.scrollTo !== "function") return;
    el.scrollTo({ top: el.scrollHeight, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [events.length, hovering]);

  return (
    <div
      ref={containerRef}
      role="log"
      aria-live="polite"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      className="flex max-h-80 flex-col gap-1.5 overflow-y-auto rounded-md border border-border bg-card p-3 text-sm"
    >
      {events.length === 0 ? (
        <div className="text-muted-foreground">No events yet</div>
      ) : (
        events.map((event, i) => (
          <EventRow key={`${event.topic}-${event.ts}-${i}`} event={event} />
        ))
      )}
    </div>
  );
}

/** Exported so ActivityPage can reuse the same row rendering under virtualization. */
export function EventRow({ event }: { event: FeedEvent }) {
  const { topic, ts, ...rest } = event;

  if (topic === "IntentBlocked") {
    const rule = String((rest as { rule?: unknown }).rule ?? "");
    return (
      <div data-testid="event-row" className="flex items-center gap-2">
        <span className="font-mono tabnum shrink-0 text-xs text-muted-foreground">
          {formatTs(ts)}
        </span>
        <Badge
          variant="outline"
          className={cn("shrink-0 border-transparent bg-blocked/15 text-blocked")}
        >
          {rule}
        </Badge>
        <span className="truncate text-muted-foreground">{detailText(rest, ["rule"])}</span>
      </div>
    );
  }

  return (
    <div data-testid="event-row" className="flex items-center gap-2">
      <span className="font-mono tabnum shrink-0 text-xs text-muted-foreground">
        {formatTs(ts)}
      </span>
      <span className="shrink-0 font-medium">{topic}</span>
      <span className="truncate text-muted-foreground">{detailText(rest)}</span>
    </div>
  );
}

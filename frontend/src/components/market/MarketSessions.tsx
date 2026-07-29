import { sessionStates, type SessionState } from "@/lib/sessions";
import { useNow } from "@/lib/useNow";
import { cn } from "@/lib/utils";

const MINUTES_IN_DAY = 1440;

type Segment = [number, number];

/** Splits a start/end window into 1-2 non-wrapping segments over [0,1440). */
function toSegments(start: number, end: number): Segment[] {
  if (start <= end) return [[start, end]];
  return [
    [start, MINUTES_IN_DAY],
    [0, end],
  ];
}

function intersectSegments(a: Segment[], b: Segment[]): Segment[] {
  const out: Segment[] = [];
  for (const [aStart, aEnd] of a) {
    for (const [bStart, bEnd] of b) {
      const start = Math.max(aStart, bStart);
      const end = Math.min(aEnd, bEnd);
      if (start < end) out.push([start, end]);
    }
  }
  return out;
}

function pct(min: number): string {
  return `${(min / MINUTES_IN_DAY) * 100}%`;
}

const SESSION_BAND_CLASS: Record<string, string> = {
  sydney: "bg-info/35",
  tokyo: "bg-warning/35",
  london: "bg-accent/35",
  newyork: "bg-profit/35",
};

/**
 * 24h session timeline + status chips, driven by `sessionStates()` (T9).
 * Pass `now` for deterministic rendering (tests); defaults to a live tick.
 */
export function MarketSessions({ now, className }: { now?: Date; className?: string }) {
  const ticking = useNow();
  const at = now ?? ticking;
  const { sessions, overlaps, weekendClosed } = sessionStates(at);
  const nowMin = at.getUTCHours() * 60 + at.getUTCMinutes();
  const byId = new Map(sessions.map((s) => [s.id, s]));

  const activeOverlaps = overlaps.filter((o) => o.active);
  const overlapBands = activeOverlaps.flatMap((o) => {
    const a = byId.get(o.ids[0]);
    const b = byId.get(o.ids[1]);
    if (!a || !b) return [];
    const segs = intersectSegments(
      toSegments(a.startUtcMin, a.endUtcMin),
      toSegments(b.startUtcMin, b.endUtcMin)
    );
    return segs.map((seg) => ({ ids: o.ids, seg }));
  });
  const featuredOverlap = activeOverlaps.find(
    (o) => o.ids.includes("london") && o.ids.includes("newyork")
  ) ?? activeOverlaps[0];

  return (
    <div
      className={cn(
        "flex flex-col gap-4 rounded-lg border border-border bg-surface-1 p-4",
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Market Sessions
        </h3>
        {featuredOverlap && (
          <span className="rounded-full border border-accent/40 bg-accent/15 px-2 py-0.5 text-xs font-medium text-accent">
            {byId.get(featuredOverlap.ids[0])?.label} × {byId.get(featuredOverlap.ids[1])?.label}{" "}
            overlap
          </span>
        )}
      </div>

      {weekendClosed ? (
        <div
          data-testid="weekend-closed-banner"
          className="flex items-center justify-center rounded-md border border-border bg-surface-2 py-6 text-sm text-muted-foreground"
        >
          Markets closed — opens Sunday
        </div>
      ) : (
        <>
          <div
            data-testid="session-timeline"
            className="relative h-8 w-full overflow-hidden rounded-md bg-surface-2"
          >
            {sessions.map((session) =>
              toSegments(session.startUtcMin, session.endUtcMin).map((seg, i) => (
                <div
                  key={`${session.id}-${i}`}
                  className={cn("absolute inset-y-0 rounded-sm", SESSION_BAND_CLASS[session.id])}
                  style={{ left: pct(seg[0]), width: pct(seg[1] - seg[0]) }}
                  aria-hidden
                />
              ))
            )}
            {overlapBands.map(({ ids, seg }, i) => (
              <div
                key={`overlap-${ids.join("-")}-${i}`}
                className={cn(
                  "absolute inset-y-0 rounded-sm bg-accent/50",
                  ids.includes("london") && ids.includes("newyork") && "bg-accent/80"
                )}
                style={{ left: pct(seg[0]), width: pct(seg[1] - seg[0]) }}
                aria-hidden
              />
            ))}
            <div
              data-testid="now-marker"
              className="absolute inset-y-0 w-px bg-foreground"
              style={{ left: pct(nowMin) }}
              aria-hidden
            />
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {sessions.map((session) => (
              <SessionChip key={session.id} session={session} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SessionChip({ session }: { session: SessionState }) {
  return (
    <div
      data-testid={`session-chip-${session.id}`}
      className="flex flex-col gap-1 rounded-md border border-border bg-surface-2 px-3 py-2"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{session.label}</span>
        <span className="font-mono tabnum text-xs text-muted-foreground">
          {session.localTime}
        </span>
      </div>
      {session.open ? (
        <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-profit/15 px-2 py-0.5 text-xs font-medium text-profit">
          <span className="size-1.5 animate-pulse rounded-full bg-profit" aria-hidden />
          Open
        </span>
      ) : (
        <span className="w-fit rounded-full bg-surface-1 px-2 py-0.5 font-mono tabnum text-xs text-muted-foreground">
          {session.statusLabel}
        </span>
      )}
    </div>
  );
}

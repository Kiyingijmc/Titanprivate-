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

/**
 * Session identity colours, resolved from design tokens rather than hex
 * literals — see src/design/tokens.css. Values stay full `hsl(var(--x))`
 * strings because they are consumed from inline `style`, not Tailwind classes.
 * Fixed hues — deliberately independent of the app accent so they never clash
 * with the violet↔blue toggle. Each session's timeline band AND its clock
 * card use this same color, so the card reads as "this is that band".
 */
const SESSION_COLORS: Record<string, string> = {
  sydney: "hsl(var(--session-sydney))",
  tokyo: "hsl(var(--session-tokyo))",
  london: "hsl(var(--session-london))",
  newyork: "hsl(var(--session-newyork))",
};

/** Timeline band fill: ~70% — vivid, still lets the now-marker + overlaps read. */
const sessionBand = (id: string) => `hsl(var(--session-${id}) / 0.70)`;

/**
 * 24h session timeline + status chips, driven by `sessionStates()` (T9).
 * Pass `now` for deterministic rendering (tests); defaults to a live tick.
 */
export function MarketSessions({
  now,
  hasCrypto = false,
  className,
}: {
  now?: Date;
  /** From the snapshot's market block — a 24/7 instrument in the book means a
   *  weekend is not a closure, so the timeline keeps rendering. */
  hasCrypto?: boolean;
  className?: string;
}) {
  const ticking = useNow();
  const at = now ?? ticking;
  const { sessions, overlaps, fxClosed, allClosed } = sessionStates(at, { hasCrypto });
  const nowMin = at.getUTCHours() * 60 + at.getUTCMinutes();
  const byId = new Map(sessions.map((s) => [s.id, s]));

  // Suppress the overlap badge whenever the FX cash market is shut. It used to
  // be computed outside the closed branch, so the card could show a live
  // "Tokyo × London overlap" chip sitting directly on top of its own
  // "Markets closed" banner.
  const activeOverlaps = fxClosed ? [] : overlaps.filter((o) => o.active);
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

      {allClosed ? (
        <div
          data-testid="weekend-closed-banner"
          className="flex items-center justify-center rounded-md border border-border bg-surface-2 py-6 text-sm text-muted-foreground"
        >
          {/* Was "opens Sunday", which read as wrong when you looked at it on a
              Sunday. Name the actual reopen instant instead. */}
          Markets closed — FX reopens Sunday 22:00 UTC
        </div>
      ) : (
        <>
          {fxClosed && (
            <div
              data-testid="crypto-only-note"
              className="rounded-md border border-border bg-surface-2 px-3 py-2 text-xs text-muted-foreground"
            >
              FX closed — crypto trades through the weekend, so the engine is still live.
            </div>
          )}
          <div
            data-testid="session-timeline"
            className="relative h-8 w-full overflow-hidden rounded-md bg-surface-2"
          >
            {sessions.map((session) =>
              toSegments(session.startUtcMin, session.endUtcMin).map((seg, i) => (
                <div
                  key={`${session.id}-${i}`}
                  className="absolute inset-y-0 rounded-sm"
                  style={{
                    left: pct(seg[0]),
                    width: pct(seg[1] - seg[0]),
                    backgroundColor: sessionBand(session.id),
                  }}
                  aria-hidden
                />
              ))
            )}
            {/* Overlap = both sessions open: brighten the stacked bands so peak
                liquidity windows (esp. London × New York) visibly glow. */}
            {overlapBands.map(({ ids, seg }, i) => (
              <div
                key={`overlap-${ids.join("-")}-${i}`}
                className="absolute inset-y-0 rounded-sm"
                style={{
                  left: pct(seg[0]),
                  width: pct(seg[1] - seg[0]),
                  backgroundColor:
                    ids.includes("london") && ids.includes("newyork")
                      ? "rgba(255,255,255,0.32)"
                      : "rgba(255,255,255,0.18)",
                }}
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
              <SessionChip key={session.id} session={session} color={SESSION_COLORS[session.id]} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SessionChip({ session, color }: { session: SessionState; color: string }) {
  const wash = `hsl(var(--session-${session.id}) / 0.08)`;
  const chipBg = `hsl(var(--session-${session.id}) / 0.15)`;
  return (
    <div
      data-testid={`session-chip-${session.id}`}
      className="flex flex-col gap-1 rounded-md border border-l-2 border-border bg-surface-2 px-3 py-2"
      style={{
        borderLeftColor: color,
        // A faint session-color wash over the card surface while the market is open.
        ...(session.open ? { boxShadow: `inset 0 0 0 9999px ${wash}` } : {}),
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold" style={{ color }}>
          {session.label}
        </span>
        {/* Live HH:MM:SS in the session's own timezone — ticks every second. */}
        <span className="font-mono tabnum text-xs text-secondary-foreground">{session.localClock}</span>
      </div>
      {session.open ? (
        <span
          className="inline-flex w-fit items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
          style={{ backgroundColor: chipBg, color }}
        >
          {/* Static dot. It used to pulse forever, which is the highest-
              frequency animation in the app: always on screen, always moving,
              on a surface the operator watches for hours. The chip already
              says "Open" in the session colour, so the motion carried no
              information it was not already showing. */}
          <span
            className="size-1.5 rounded-full"
            style={{ backgroundColor: color }}
            aria-hidden
          />
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

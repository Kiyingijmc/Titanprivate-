import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { Panel, type PanelStatus } from "@/components/shell/Panel";
import { StatTiles } from "@/components/StatTiles";
import { RiskPanel } from "@/components/RiskPanel";
import { EquitySparkline } from "@/components/EquitySparkline";
import { RangeSelector, enabledRangeNames, lookupRangeSeconds } from "@/components/RangeSelector";
import { Controls } from "@/components/Controls";
import { MarketSessions } from "@/components/market/MarketSessions";
import { LocalityClock } from "@/components/market/LocalityClock";
import { DollarBias } from "@/components/market/DollarBias";
import { NewsPanel } from "@/components/market/NewsPanel";
import { Badge } from "@/components/ui/badge";
import { SideChip } from "@/components/SideChip";
import { useController } from "@/context/ControllerContext";
import { useReadOnly } from "@/context/ReadOnlyContext";
import { useEquityBuffer } from "@/lib/useEquityBuffer";
import { useEquitySeries } from "@/lib/useEquitySeries";
import { useLiveEquityTail, type LiveEquityPoint } from "@/lib/useLiveEquityTail";
import { signedPnl, pnlToneClass } from "@/lib/format";
import type { Position, FeedEvent, RangeName, EquitySeries, EquityPoint } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY_S = 86_400;

/**
 * Stitches the live WS leading edge onto the end of a fetched series.
 *
 * The fetched series is only as fresh as the recorder's `flush_interval_s`
 * (60s) plus a bucket plus the poll interval — polling faster can't get
 * anything newer, so the panel otherwise looks frozen, and on the DEFAULT `1d`
 * range its readout disagreed with the live `snapshot.account.equity` KPI tile
 * three inches away on the same screen. Two different "current equity" numbers
 * on the view the operator lands on is not a cosmetic problem.
 *
 * RESOLUTION RULE — the tail's shape depends on the tier, not just on whether
 * one is drawn:
 *  - FINE tier (15m/30m/1h/4h/12h): the full per-heartbeat tail. The fetched
 *    line is already ~30s-resolution, so the tail matches it.
 *  - COARSE tier within a day (`1d`): exactly ONE leading point carrying
 *    current equity. Appending the raw per-heartbeat stream to a 300s-bucketed
 *    line would draw high-resolution detail the rest of the line does not have
 *    — fabricated resolution, the chart's own kind of lie. One point gives a
 *    truthful leading edge without inventing texture.
 *  - Wider than a day (1w/1mo/…): no tail at all. A single live point is
 *    invisible at that scale and only widens the domain.
 *
 * CLOCKS — `tail` timestamps are BROWSER time (`clientTs`); `series.points[].ts`
 * is SERVER time. They are translated with `serverOffset` before any comparison
 * (see `serverClockOffset`). Comparing them raw made a slow client render no
 * tail at all, silently, and a fast client plot points in the future.
 *
 * NO-DOUBLE-COUNT — only translated points STRICTLY NEWER than the series' last
 * real (non-null) point are appended; anything at or before that instant is
 * already in the fetched data. The tail is sorted before appending, so the
 * merged `points` array stays ascending in `ts`.
 *
 * TIME BOUND — the tail is clamped to the selected range's own width, not just
 * to a point count. Under a poll outage the fetched data freezes while the tail
 * keeps growing, so a count-only bound let a chart labelled "15m" quietly span
 * hours of live samples. (The frozen fetched block itself still renders; the
 * panel's refresh-failure badge is what makes that visible rather than silent.)
 */
export function withLiveTail(
  series: EquitySeries | null,
  tail: LiveEquityPoint[],
  serverOffset = 0,
): EquitySeries | null {
  if (!series) return series;

  const width = lookupRangeSeconds(series.range);
  const fine = series.tier === "fine";
  // Unknown range width is treated as "too wide to tail" — fail closed.
  if (!fine && (width === null || width > DAY_S)) return series;

  let lastReal: EquityPoint | null = null;
  for (let i = series.points.length - 1; i >= 0; i--) {
    const p = series.points[i];
    if (p !== null && Number.isFinite(p.ts)) {
      lastReal = p;
      break;
    }
  }
  if (lastReal === null) return series; // nothing to anchor a "newer than" comparison against

  const translated = tail
    .map((t) => ({ ts: t.clientTs + serverOffset, equity: t.equity }))
    .filter((t) => Number.isFinite(t.ts) && Number.isFinite(t.equity))
    .sort((a, b) => a.ts - b.ts);
  if (translated.length === 0) return series;

  const newestTail = translated[translated.length - 1].ts;
  const windowed = width === null ? translated : translated.filter((t) => t.ts >= newestTail - width);

  const fresh = windowed.filter((t) => t.ts > lastReal!.ts);
  if (fresh.length === 0) return series;

  // Peak is a running max over EVERYTHING observed since the last fetched
  // point, even on the coarse path where the intermediate samples are not
  // drawn — an equity high we saw is a real high whether or not it has a pixel.
  let runningPeak = typeof lastReal.peak === "number" && Number.isFinite(lastReal.peak)
    ? lastReal.peak
    : lastReal.equity;
  const peakAt = new Map<number, number>();
  for (const t of fresh) {
    runningPeak = Math.max(runningPeak, t.equity);
    peakAt.set(t.ts, runningPeak);
  }

  // Balance isn't sampled by the live tail (only equity is), so it carries
  // forward the last known real balance rather than fabricating one — a
  // truthful "no new information" rather than a guess.
  const lastBalance = typeof lastReal.balance === "number" && Number.isFinite(lastReal.balance)
    ? lastReal.balance
    : undefined;

  const kept = fine ? fresh : [fresh[fresh.length - 1]];
  const extra: EquityPoint[] = kept.map((t) => ({
    ts: t.ts,
    equity: t.equity,
    balance: lastBalance,
    peak: peakAt.get(t.ts) ?? runningPeak,
  }));

  return { ...series, points: [...series.points, ...extra] };
}

function TopPositionRow({ position }: { position: Position }) {
  const pnl = signedPnl(position.pnl);
  return (
    <Link
      to="/positions"
      className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex items-center gap-2">
        <span className="font-medium">{position.symbol}</span>
        <SideChip side={position.side} />
      </span>
      <span className={cn("font-mono tabnum", pnlToneClass(pnl.tone))}>{pnl.text}</span>
    </Link>
  );
}

function detailText(event: FeedEvent): string {
  const { topic, ts, ...rest } = event;
  void topic;
  void ts;
  const entries = Object.entries(rest);
  if (entries.length === 0) return "";
  return entries.map(([k, v]) => `${k}=${String(v)}`).join(" ");
}

function RecentEventRow({ event }: { event: FeedEvent }) {
  const blocked = event.topic === "IntentBlocked";
  return (
    <Link
      to="/activity"
      className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {blocked ? (
        <Badge variant="outline" className="shrink-0 border-transparent bg-blocked/15 text-blocked">
          {event.topic}
        </Badge>
      ) : (
        <span className="shrink-0 font-medium">{event.topic}</span>
      )}
      <span className="truncate text-muted-foreground">{detailText(event)}</span>
    </Link>
  );
}

/**
 * At-a-glance Overview (design-system §5): KPI row + equity trend + a compact
 * top-positions summary + recent activity + global controls, each independently
 * Panel-wrapped so a stale/loading connection degrades gracefully per block.
 */
export default function OverviewPage() {
  const { snapshot, events, connectionStatus, api } = useController();
  const { readOnly, setReadOnly } = useReadOnly();
  // KEPT ON PURPOSE (not dead): this WS-only buffer is the fallback the equity
  // panel falls back TO when `/api/equity` has never succeeded — `equity.data`
  // is then null, `equitySeriesForChart` is null, and `EquitySparkline` renders
  // this buffer instead of an empty panel. Retiring it would turn a degraded
  // backend into a blank chart. Its cost (a small localStorage write per
  // distinct equity value) is accepted for that; see M4 in the fix report.
  const equityPoints = useEquityBuffer(snapshot?.account.equity);
  const [range, setRange] = useState<RangeName>("1d");
  const equity = useEquitySeries(api, range);
  const liveEquityTail = useLiveEquityTail(snapshot?.account.equity);
  const equitySeriesForChart = withLiveTail(equity.data, liveEquityTail, equity.serverOffset);

  const firstSampleTs = equity.data?.coverage.first_sample_ts ?? null;
  const { serverOffset } = equity;
  // Server-clock "now". Every comparison against a server `ts` goes through
  // this, never a raw Date.now() — see `serverClockOffset`.
  const serverNow = useCallback(() => Date.now() / 1000 + serverOffset, [serverOffset]);

  // `[` / `]` step the lookback across the ENABLED ranges (spec'd global
  // shortcut). Guarded against text entry and against the ⌘K/Ctrl-K palette's
  // modifier so the two handlers can't both fire.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "[" && e.key !== "]") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      const list = enabledRangeNames(firstSampleTs, serverNow());
      if (list.length === 0) return;
      e.preventDefault();
      const widen = e.key === "]";
      setRange((cur) => {
        const i = list.indexOf(cur);
        if (i === -1) return list[0];
        // Clamped, not wrapping: `]` at the widest range should stay put rather
        // than silently jumping back to 15m.
        const next = widen ? Math.min(i + 1, list.length - 1) : Math.max(i - 1, 0);
        return list[next];
      });
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [firstSampleTs, serverNow]);

  const baseStatus: PanelStatus = snapshot === null ? "loading" : connectionStatus.stale ? "stale" : "populated";

  // C1: `useEquitySeries` deliberately keeps the last good series on a failed
  // refresh, so a dead `/api/equity` renders a perfectly plausible frozen curve.
  // The WS snapshot is a SEPARATE transport and stays healthy through it, so the
  // panel's base status cannot see this at all. Surface it explicitly: the Panel
  // goes "stale" (its own marker) AND the chart carries a visible badge naming
  // which failure it is.
  const equityStatus: PanelStatus =
    baseStatus === "loading" ? "loading" : equity.error !== null ? "stale" : baseStatus;

  const topPositions = snapshot
    ? [...snapshot.positions].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl)).slice(0, 3)
    : [];
  const positionsStatus: PanelStatus =
    snapshot === null ? "loading" : connectionStatus.stale ? "stale" : topPositions.length === 0 ? "empty" : "populated";

  const recentEvents = events.slice(-4).reverse();
  const activityStatus: PanelStatus =
    snapshot === null ? "loading" : connectionStatus.stale ? "stale" : recentEvents.length === 0 ? "empty" : "populated";

  return (
    <div className="grid gap-4">
      {/* Market Context strip (Task 12): always-on session timeline + local
          clock + USD bias + economic calendar, above the account KPIs. */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <MarketSessions hasCrypto={snapshot?.market?.has_crypto ?? false} />
        <LocalityClock />
        <DollarBias data={snapshot?.dollar} />
        <NewsPanel data={snapshot?.news} />
      </div>

      <Panel status={baseStatus} title="Overview">
        {snapshot && (
          <StatTiles
            account={snapshot.account}
            arbiter={snapshot.arbiter}
            dayPnl={snapshot.risk?.day_pnl ?? null}
            openPnl={snapshot.positions.reduce((sum, p) => sum + p.pnl, 0)}
            openCount={snapshot.positions.length}
            pendingCount={snapshot.orders?.length ?? 0}
          />
        )}
      </Panel>

      {snapshot?.risk && (
        <Panel status={baseStatus} title="Risk">
          <RiskPanel risk={snapshot.risk} />
        </Panel>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel status={equityStatus} title="Equity">
          <div className="mb-3 flex justify-end">
            <RangeSelector
              value={range}
              onChange={setRange}
              firstSampleTs={firstSampleTs}
              loadError={equity.error !== null}
              now={serverNow()}
            />
          </div>
          {equity.error && (
            <div
              data-testid="equity-fetch-error"
              role="status"
              className="mb-2 flex items-start gap-1.5 rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-warning"
            >
              <AlertTriangle className="mt-px size-3 shrink-0" />
              <span>
                {equity.data
                  ? "Equity history could not be refreshed — the curve below is not current."
                  : "Equity history could not be loaded."}{" "}
                {equity.error.detail}
              </span>
            </div>
          )}
          <div
            className={cn(
              "transition-opacity duration-[var(--motion-fast)]",
              // Dim on a failed refresh too, not only while loading: the `finally`
              // in useEquitySeries clears `loading` on the failure path, so a dim
              // keyed on loading alone snaps back to full confidence the instant
              // the fetch dies.
              (equity.loading || equity.error !== null) && equity.data && "opacity-60",
            )}
          >
            <EquitySparkline points={equityPoints} series={equitySeriesForChart ?? undefined} />
          </div>
        </Panel>
        <Panel status={baseStatus} title="Controls">
          <Controls
            api={api}
            paused={snapshot?.health.paused ?? false}
            readOnly={readOnly}
            onResult={(r) => {
              if (r.readOnly) setReadOnly(true);
            }}
          />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel status={positionsStatus} title="Top Positions" emptyMessage="No open positions">
          <div className="flex flex-col gap-1">
            {topPositions.map((p) => (
              <TopPositionRow key={p.ticket} position={p} />
            ))}
          </div>
        </Panel>

        <Panel status={activityStatus} title="Recent Activity" emptyMessage="No events yet">
          <div className="flex flex-col gap-1">
            {recentEvents.map((e, i) => (
              <RecentEventRow key={`${e.topic}-${e.ts}-${i}`} event={e} />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

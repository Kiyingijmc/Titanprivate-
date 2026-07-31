import { useState } from "react";
import { Link } from "react-router-dom";
import { Panel, type PanelStatus } from "@/components/shell/Panel";
import { StatTiles } from "@/components/StatTiles";
import { EquitySparkline } from "@/components/EquitySparkline";
import { RangeSelector } from "@/components/RangeSelector";
import { Controls } from "@/components/Controls";
import { MarketSessions } from "@/components/market/MarketSessions";
import { LocalityClock } from "@/components/market/LocalityClock";
import { DollarBias } from "@/components/market/DollarBias";
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

/**
 * Stitches the live WS leading edge onto the end of a fetched series.
 *
 * The fetched series is only as fresh as the recorder's `flush_interval_s`
 * (60s) — polling faster can't get anything newer, so the panel otherwise
 * looks frozen between poll ticks. The live tail fills that gap, but only
 * for FINE-tier ranges (15m/30m/1h/4h/12h): a coarse range's bucket is 300s+
 * wide, and drawing per-heartbeat points at its right edge would fabricate a
 * high-resolution spike the rest of the line doesn't have — its own kind of
 * lie, so coarse ranges are returned untouched.
 *
 * No-double-count rule: only tail points with `ts` STRICTLY GREATER than the
 * fetched series' last real (non-null) point are appended. Anything at or
 * before that instant is already represented in the fetched data — appending
 * it too would plot the same moment twice. Because the tail is filtered to
 * ts values greater than the last fetched point and is itself chronological,
 * the merged `points` array stays ascending in `ts`, so nothing gets
 * reordered.
 */
export function withLiveTail(series: EquitySeries | null, tail: LiveEquityPoint[]): EquitySeries | null {
  if (!series || series.tier !== "fine") return series;

  let lastReal: EquityPoint | null = null;
  for (let i = series.points.length - 1; i >= 0; i--) {
    const p = series.points[i];
    if (p !== null) {
      lastReal = p;
      break;
    }
  }
  if (lastReal === null) return series; // nothing to anchor a "newer than" comparison against

  const fresh = tail.filter((t) => t.ts > lastReal!.ts).sort((a, b) => a.ts - b.ts);
  if (fresh.length === 0) return series;

  // Balance isn't sampled by the live tail (only equity is), so it carries
  // forward the last known real balance rather than fabricating one — a
  // truthful "no new information" rather than a guess. Peak/drawdown DO
  // update: we know the true running max of (last real peak, live equity).
  let runningPeak = typeof lastReal.peak === "number" ? lastReal.peak : lastReal.equity;
  const lastBalance = lastReal.balance;
  const extra: EquityPoint[] = fresh.map((t) => {
    runningPeak = Math.max(runningPeak, t.equity);
    return { ts: t.ts, equity: t.equity, balance: lastBalance, peak: runningPeak };
  });

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
  const equityPoints = useEquityBuffer(snapshot?.account.equity);
  const [range, setRange] = useState<RangeName>("1d");
  const equity = useEquitySeries(api, range);
  const liveEquityTail = useLiveEquityTail(snapshot?.account.equity);
  const equitySeriesForChart = withLiveTail(equity.data, liveEquityTail);

  const baseStatus: PanelStatus = snapshot === null ? "loading" : connectionStatus.stale ? "stale" : "populated";

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
          clock + USD bias, above the account KPIs. */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <MarketSessions />
        <LocalityClock />
        <DollarBias data={snapshot?.dollar} />
      </div>

      <Panel status={baseStatus} title="Overview">
        {snapshot && (
          <StatTiles
            account={snapshot.account}
            arbiter={snapshot.arbiter}
            dayPnl={snapshot.account.equity - snapshot.account.balance}
            openPnl={snapshot.positions.reduce((sum, p) => sum + p.pnl, 0)}
            openCount={snapshot.positions.length}
          />
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel status={baseStatus} title="Equity">
          <div className="mb-3 flex justify-end">
            <RangeSelector
              value={range}
              onChange={setRange}
              firstSampleTs={equity.data?.coverage.first_sample_ts ?? null}
            />
          </div>
          <div
            className={cn(
              "transition-opacity duration-[var(--motion-fast)]",
              equity.loading && equity.data && "opacity-60",
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

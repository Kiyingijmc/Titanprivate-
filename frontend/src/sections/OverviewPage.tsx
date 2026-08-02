import { Link } from "react-router-dom";
import { Panel, type PanelStatus } from "@/components/shell/Panel";
import { StatTiles } from "@/components/StatTiles";
import { RiskPanel } from "@/components/RiskPanel";
import { EquitySparkline } from "@/components/EquitySparkline";
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
import { signedPnl, pnlToneClass } from "@/lib/format";
import type { Position, FeedEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

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
        <Panel status={baseStatus} title="Equity">
          <EquitySparkline points={equityPoints} />
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

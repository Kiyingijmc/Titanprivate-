import { Link } from "react-router-dom";
import { Panel, type PanelStatus } from "@/components/shell/Panel";
import { StatTiles } from "@/components/StatTiles";
import { EquitySparkline } from "@/components/EquitySparkline";
import { Controls } from "@/components/Controls";
import { Badge } from "@/components/ui/badge";
import { useController } from "@/context/ControllerContext";
import { useReadOnly } from "@/context/ReadOnlyContext";
import { useEquityBuffer } from "@/lib/useEquityBuffer";
import { signedPnl } from "@/lib/format";
import type { Position, FeedEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

function SideChip({ side }: { side: "BUY" | "SELL" }) {
  const tone = side === "BUY" ? "profit" : "loss";
  return (
    <Badge
      variant="outline"
      data-tone={tone}
      className={cn("border-transparent", tone === "profit" ? "bg-profit/15 text-profit" : "bg-loss/15 text-loss")}
    >
      {side}
    </Badge>
  );
}

function TopPositionRow({ position }: { position: Position }) {
  const pnl = signedPnl(position.pnl);
  const pnlToneClass = { profit: "text-profit", loss: "text-loss", flat: "text-muted-foreground" }[pnl.tone];
  return (
    <Link
      to="/positions"
      className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex items-center gap-2">
        <span className="font-medium">{position.symbol}</span>
        <SideChip side={position.side} />
      </span>
      <span className={cn("font-mono tabnum", pnlToneClass)}>{pnl.text}</span>
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
      <Panel status={baseStatus} title="Overview">
        {snapshot && (
          <StatTiles
            account={snapshot.account}
            arbiter={snapshot.arbiter}
            dayPnl={snapshot.account.equity - snapshot.account.balance}
            openCount={snapshot.positions.length}
          />
        )}
      </Panel>

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

import type { ReactNode } from "react";
import { Wifi, WifiOff, Loader2, CloudOff, Clock, Pause, Gauge, Command } from "lucide-react";
import type { ConnectionState, ConnectionStatus } from "@/lib/connection";
import type { Snapshot } from "@/lib/types";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";

type Tone = "profit" | "warning" | "loss" | "muted" | "accent";

const TONE_CLASS: Record<Tone, string> = {
  profit: "text-profit",
  warning: "text-warning",
  loss: "text-loss",
  muted: "text-muted-foreground",
  accent: "text-accent",
};

function StatusChip({ tone, icon, children }: { tone: Tone; icon: ReactNode; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm font-medium", TONE_CLASS[tone])}>
      {icon}
      <span>{children}</span>
    </span>
  );
}

const CONNECTION_PRESENTATION: Record<
  ConnectionStatus,
  { tone: Tone; label: string; icon: ReactNode; spin?: boolean }
> = {
  live: { tone: "profit", label: "Live", icon: <Wifi className="size-4" aria-hidden /> },
  reconnecting: { tone: "warning", label: "Reconnecting", icon: <Loader2 className="size-4 animate-spin" aria-hidden /> },
  degraded: { tone: "warning", label: "Degraded", icon: <CloudOff className="size-4" aria-hidden /> },
  offline: { tone: "loss", label: "Offline", icon: <WifiOff className="size-4" aria-hidden /> },
  connecting: { tone: "muted", label: "Connecting", icon: <Loader2 className="size-4 animate-spin" aria-hidden /> },
};

export interface StatusBarProps {
  connection: ConnectionState;
  snapshot: Snapshot | null;
  onOpenPalette: () => void;
}

export function StatusBar({ connection, snapshot, onOpenPalette }: StatusBarProps) {
  const conn = CONNECTION_PRESENTATION[connection.status];

  return (
    <div className="flex h-12 shrink-0 items-center gap-4 border-b border-border bg-surface-1 px-4">
      {/* Scoped live region: only the system-status cluster is announced — NOT the
          account figures, which change every tick and would make a screen reader noisy. */}
      <div className="flex items-center gap-4" role="status" aria-live="polite" aria-label="System status">
      <StatusChip tone={conn.tone} icon={conn.icon}>
        {conn.label}
      </StatusChip>

      {connection.stale && (
        <StatusChip tone="warning" icon={<Clock className="size-4" aria-hidden />}>
          Stale
        </StatusChip>
      )}

      {snapshot?.health.paused && (
        <StatusChip tone="warning" icon={<Pause className="size-4" aria-hidden />}>
          Paused
        </StatusChip>
      )}

      {snapshot?.arbiter.throttle.enabled && (
        <StatusChip tone="warning" icon={<Gauge className="size-4" aria-hidden />}>
          Throttle &times;<span className="font-mono tabnum">{snapshot.arbiter.throttle.current_mult}</span>
        </StatusChip>
      )}
      </div>

      <div className="ml-auto flex items-center gap-4">
        <div className="flex items-center gap-3 font-mono tabnum text-sm text-secondary-foreground">
          <span>
            Balance <span className="text-foreground">{snapshot ? money(snapshot.account.balance) : "—"}</span>
          </span>
          <span>
            Equity <span className="text-foreground">{snapshot ? money(snapshot.account.equity) : "—"}</span>
          </span>
        </div>

        <button
          type="button"
          onClick={onOpenPalette}
          aria-label="Open command palette"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-sm text-muted-foreground",
            "hover:bg-surface-2 hover:text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
        >
          <Command className="size-4" aria-hidden />
          <span>&#8984;K</span>
        </button>
      </div>
    </div>
  );
}

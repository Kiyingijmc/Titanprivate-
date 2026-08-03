import type { ReactNode } from "react";
import { Wifi, WifiOff, Loader2, CloudOff, Clock, Pause, Gauge, Command, ArrowUp, ArrowDown, Minus } from "lucide-react";
import type { ConnectionState, ConnectionStatus } from "@/lib/connection";
import type { Snapshot } from "@/lib/types";
import { money, signedPnl, pnlToneClass } from "@/lib/format";
import { sessionStates } from "@/lib/sessions";
import { useNow } from "@/lib/useNow";
import { cn } from "@/lib/utils";
import { AccentToggle } from "./AccentToggle";

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

function fmtCountdown(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/**
 * Condensed, always-visible market context: the active session name(s) plus a
 * mini next-open countdown, and a compact dollar-bias pill. Reads its own clock
 * via useNow (kept OUT of the aria-live status cluster — the countdown ticks
 * every second and would make a screen reader noisy). Collapses on narrow
 * widths so the bar never overflows.
 */
function CondensedMarketContext({ snapshot }: { snapshot: Snapshot | null }) {
  const now = useNow();
  const hasCrypto = snapshot?.market?.has_crypto ?? false;
  const { sessions, fxClosed, allClosed } = sessionStates(now, { hasCrypto });
  const open = sessions.filter((s) => s.open);
  const nextOpen = sessions
    .filter((s) => !s.open)
    .sort((a, b) => a.countdownMin - b.countdownMin)[0];

  const dollar = snapshot?.dollar;
  const showDollar = dollar != null && dollar.source !== "unavailable";
  const dir = showDollar ? (dollar.bias > 0 ? "up" : dollar.bias < 0 ? "down" : "flat") : "flat";
  const DirIcon = dir === "up" ? ArrowUp : dir === "down" ? ArrowDown : Minus;

  return (
    <div className="hidden items-center gap-3 lg:flex">
      <span
        data-testid="statusbar-sessions"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"
      >
        <Clock className="size-4" aria-hidden />
        {allClosed ? (
          <span>Markets closed</span>
        ) : fxClosed ? (
          // FX shut but the book holds a 24/7 instrument: say so rather than
          // claiming a closure the engine does not observe.
          <span className="font-medium text-secondary-foreground">Crypto only</span>
        ) : open.length > 0 ? (
          <span>
            <span className="font-medium text-secondary-foreground">
              {open.map((s) => s.label).join(" + ")}
            </span>
          </span>
        ) : (
          <span>
            No session
            {nextOpen && (
              <span className="text-muted-foreground">
                {" "}
                &middot; {nextOpen.label} in{" "}
                <span className="font-mono tabnum">{fmtCountdown(nextOpen.countdownMin)}</span>
              </span>
            )}
          </span>
        )}
      </span>

      {showDollar && (
        <span
          data-testid="statusbar-dollar"
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-sm text-muted-foreground"
          title="USD bias"
        >
          <span className="text-xs uppercase tracking-wide">USD</span>
          <DirIcon className="size-3.5" aria-hidden />
          <span className="font-mono tabnum text-secondary-foreground">
            {dollar.bias > 0 ? "+" : ""}
            {dollar.bias.toFixed(0)}
          </span>
        </span>
      )}
    </div>
  );
}

export interface StatusBarProps {
  connection: ConnectionState;
  snapshot: Snapshot | null;
  onOpenPalette: () => void;
}

export function StatusBar({ connection, snapshot, onOpenPalette }: StatusBarProps) {
  const conn = CONNECTION_PRESENTATION[connection.status];
  // Live floating P&L across all open orders (Σ position.pnl) — always visible.
  const openPnl = snapshot ? signedPnl(snapshot.positions.reduce((s, p) => s + p.pnl, 0)) : null;

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

      <CondensedMarketContext snapshot={snapshot} />

      <div className="ml-auto flex items-center gap-4">
        <div className="flex items-center gap-3 font-mono tabnum text-sm text-secondary-foreground">
          <span>
            Balance <span className="text-foreground">{snapshot ? money(snapshot.account.balance) : "—"}</span>
          </span>
          <span>
            Equity <span className="text-foreground">{snapshot ? money(snapshot.account.equity) : "—"}</span>
          </span>
          {openPnl && (
            <span className="hidden sm:inline" data-testid="statusbar-openpnl">
              Open P&L{" "}
              <span className={cn(pnlToneClass(openPnl.tone))}>{openPnl.text}</span>
            </span>
          )}
        </div>

        <AccentToggle />

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

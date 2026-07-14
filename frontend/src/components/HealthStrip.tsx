import type { ReactNode } from "react";
import { Wifi, WifiOff, Clock, Pause, Gauge } from "lucide-react";
import type { ArbiterBlock, Health } from "@/lib/types";
import { ageLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

function Pill({
  tone,
  icon,
  children,
}: {
  tone: "profit" | "loss" | "warning" | "info";
  icon: ReactNode;
  children: ReactNode;
}) {
  const toneClass = {
    profit: "bg-profit/15 text-profit border-profit/30",
    loss: "bg-loss/15 text-loss border-loss/30",
    warning: "bg-warning/15 text-warning border-warning/30",
    info: "bg-info/15 text-info border-info/30",
  }[tone];
  const dotClass = {
    profit: "bg-profit",
    loss: "bg-loss",
    warning: "bg-warning",
    info: "bg-info",
  }[tone];
  return (
    <div className={cn("inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm", toneClass)}>
      <span className={cn("size-1.5 rounded-full", dotClass)} aria-hidden />
      {icon}
      <span>{children}</span>
    </div>
  );
}

export function HealthStrip({ health, arbiter }: { health: Health; arbiter: ArbiterBlock }) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="status" aria-label="System health">
      {health.bridge_connected ? (
        <Pill tone="profit" icon={<Wifi className="size-4" aria-hidden />}>
          Connected
        </Pill>
      ) : (
        <Pill tone="loss" icon={<WifiOff className="size-4" aria-hidden />}>
          Stale
        </Pill>
      )}
      <Pill tone="info" icon={<Clock className="size-4" aria-hidden />}>
        Heartbeat {ageLabel(health.last_heartbeat_age_s)}
      </Pill>
      {health.paused && (
        <Pill tone="warning" icon={<Pause className="size-4" aria-hidden />}>
          Paused
        </Pill>
      )}
      {arbiter.throttle.enabled && (
        <Pill tone="warning" icon={<Gauge className="size-4" aria-hidden />}>
          Throttle {arbiter.throttle.current_mult}x
        </Pill>
      )}
    </div>
  );
}

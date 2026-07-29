import { Globe } from "lucide-react";
import { useNow } from "@/lib/useNow";
import { cn } from "@/lib/utils";

const timeFormatter = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
});

/**
 * Your local wall-clock time, date, and resolved IANA timezone. Static-state
 * — carries no session logic, just presents "now" for the viewer.
 */
export function LocalityClock({ now, className }: { now?: Date; className?: string }) {
  const ticking = useNow();
  const at = now ?? ticking;
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <div
      data-testid="locality-clock"
      className={cn(
        "flex flex-col gap-1 rounded-lg border border-border bg-surface-1 px-4 py-3",
        className
      )}
    >
      <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <Globe className="size-3.5" aria-hidden />
        <span>Local time</span>
      </div>
      <div className="font-mono tabnum text-3xl font-semibold leading-none text-foreground">
        {timeFormatter.format(at)}
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>{dateFormatter.format(at)}</span>
        <span aria-hidden>·</span>
        <span className="font-mono">{timeZone}</span>
      </div>
    </div>
  );
}

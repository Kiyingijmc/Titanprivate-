import * as React from "react";
import { AlertTriangle, Clock } from "lucide-react";

import { cn } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { MaximizeButton } from "./MaximizeButton";

export type PanelStatus = "loading" | "empty" | "error" | "populated" | "stale";

export interface PanelProps {
  status: PanelStatus;
  title?: React.ReactNode;
  actions?: React.ReactNode;
  onRetry?: () => void;
  emptyMessage?: React.ReactNode;
  errorMessage?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  /** When provided, the header shows a maximize control that calls this. */
  onMaximize?: () => void;
  /** Subject area. Adds a left border + weak header wash in the domain colour. */
  domain?: "risk" | "market" | "execution" | "analytics";
}

// A literal lookup, because Tailwind cannot see dynamically-built class names
// (e.g. `border-l-domain-${domain}` would not be picked up by the scanner).
const DOMAIN_BORDER: Record<string, string> = {
  risk: "border-l-2 border-l-domain-risk",
  market: "border-l-2 border-l-domain-market",
  execution: "border-l-2 border-l-domain-execution",
  analytics: "border-l-2 border-l-domain-analytics",
};

// Spec §8: no NEW colours for status — `stale` reuses --warning, `error`
// reuses --loss, both weak. The wash is painted as a `::before` overlay rather
// than a `bg-*` utility on the Card because `cn()` is `twMerge(clsx(...))`,
// and tailwind-merge treats any `bg-*` class as competing with the Card's own
// `bg-surface-1`, dropping whichever comes first in the merge — that would
// leave a stale/error panel with no surface at all, reading as a wash over
// the page background instead of a card. `/[0.07]` mirrors --tint-weak.
const TONE_WASH =
  "relative before:pointer-events-none before:absolute before:inset-0 before:rounded-lg before:content-['']";

const STATUS_TONE: Partial<Record<PanelStatus, { tone: string; cls: string }>> = {
  stale: { tone: "stale", cls: `${TONE_WASH} before:bg-warning/[0.07]` },
  error: { tone: "error", cls: `${TONE_WASH} before:bg-loss/[0.07]` },
};

function PanelSkeleton() {
  return (
    // Staggered ~60ms apart: pulsing in unison reads as one mechanical block,
    // offset it reads as a wave and suggests content streaming in. Purely
    // decorative and non-blocking; reduced motion stops it outright via the
    // iteration-count rule in index.css.
    <div data-testid="skeleton" className="space-y-2" aria-hidden="true">
      <div className="h-4 w-full animate-pulse rounded-md bg-surface-2" style={{ animationDelay: "0ms" }} />
      <div className="h-4 w-5/6 animate-pulse rounded-md bg-surface-2" style={{ animationDelay: "60ms" }} />
      <div className="h-4 w-2/3 animate-pulse rounded-md bg-surface-2" style={{ animationDelay: "120ms" }} />
    </div>
  );
}

function StaleMarker() {
  return (
    <div
      data-testid="stale-marker"
      className="mb-2 inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-2 py-0.5 text-xs text-warning"
    >
      <Clock className="size-3" />
      <span>data may be delayed</span>
    </div>
  );
}

export function Panel({
  status,
  title,
  actions,
  onRetry,
  emptyMessage = "Nothing to show.",
  errorMessage = "Something went wrong.",
  children,
  className,
  onMaximize,
  domain,
}: PanelProps) {
  return (
    <Card
      className={cn(
        "bg-surface-1 shadow-1",
        domain && DOMAIN_BORDER[domain],
        STATUS_TONE[status]?.cls,
        className
      )}
      data-domain={domain}
      data-tone={STATUS_TONE[status]?.tone}
    >
      {(title || actions || onMaximize) && (
        <CardHeader className="flex-row items-center justify-between space-y-0">
          {title && <CardTitle className="text-foreground">{title}</CardTitle>}
          {(actions || onMaximize) && (
            <div className="flex items-center gap-2">
              {actions}
              {onMaximize && (
                // `title` is a ReactNode; only a string can name the control for
                // assistive tech, so fall back when a caller passes an element.
                <MaximizeButton
                  title={typeof title === "string" ? title : "panel"}
                  onClick={onMaximize}
                />
              )}
            </div>
          )}
        </CardHeader>
      )}
      <CardContent>
        {status === "loading" && <PanelSkeleton />}

        {status === "empty" && (
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        )}

        {status === "error" && (
          <div className="flex flex-col items-start gap-3">
            <div className="flex items-center gap-2 text-sm text-secondary-foreground">
              <AlertTriangle className="size-4 text-warning" />
              <span>{errorMessage}</span>
            </div>
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          </div>
        )}

        {status === "populated" && children}

        {status === "stale" && (
          <div>
            <StaleMarker />
            {children}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

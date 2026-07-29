import * as React from "react";
import { AlertTriangle, Clock } from "lucide-react";

import { cn } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

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
}

function PanelSkeleton() {
  return (
    <div data-testid="skeleton" className="space-y-2" aria-hidden="true">
      <div className="h-4 w-full animate-pulse rounded-md bg-surface-2" />
      <div className="h-4 w-5/6 animate-pulse rounded-md bg-surface-2" />
      <div className="h-4 w-2/3 animate-pulse rounded-md bg-surface-2" />
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
}: PanelProps) {
  return (
    <Card className={cn("bg-surface-1", className)}>
      {(title || actions) && (
        <CardHeader className="flex-row items-center justify-between space-y-0">
          {title && <CardTitle className="text-foreground">{title}</CardTitle>}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
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

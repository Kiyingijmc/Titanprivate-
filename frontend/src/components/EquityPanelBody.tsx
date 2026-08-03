import { AlertTriangle } from "lucide-react";
import { EquitySparkline, type BufferPoint } from "@/components/EquitySparkline";
import { RangeSelector } from "@/components/RangeSelector";
import { cn } from "@/lib/utils";
import type { ApiError } from "@/lib/api";
import type { EquitySeries, RangeName, RiskBlock } from "@/lib/types";

export interface EquityPanelBodyProps {
  points: BufferPoint[];
  series?: EquitySeries;
  range: RangeName;
  onRangeChange: (range: RangeName) => void;
  firstSampleTs: number | null;
  error: ApiError | null;
  loading: boolean;
  /** `equity.data !== null`. Drives the error wording and the dim, exactly as
   *  before the extraction — NOT the same thing as `series`, which is the
   *  live-tailed derivative. */
  hasFetchedData: boolean;
  /** SERVER-clock epoch SECONDS (serverNow()), never a raw browser clock. */
  now: number;
  /** Fill the parent instead of rendering the 140px strip. */
  fill?: boolean;
  /** Today's risk block, for the breaker reference line. */
  risk?: RiskBlock;
}

/**
 * The Equity panel's body: range selector, fetch-error badge, and the chart.
 *
 * Extracted so the collapsed card and the maximized dialog render the SAME
 * component and only one of them is ever mounted (spec §6). The error badge
 * travels with it deliberately: a dead /api/equity must stay visible at 75%,
 * not just in the small card.
 */
export function EquityPanelBody({
  points,
  series,
  range,
  onRangeChange,
  firstSampleTs,
  error,
  loading,
  hasFetchedData,
  now,
  fill = false,
  risk,
}: EquityPanelBodyProps) {
  return (
    <div className={cn("flex flex-col", fill && "min-h-0 flex-1")}>
      <div className="mb-3 flex justify-end">
        <RangeSelector
          value={range}
          onChange={onRangeChange}
          firstSampleTs={firstSampleTs}
          loadError={error !== null}
          now={now}
        />
      </div>

      {error && (
        <div
          data-testid="equity-fetch-error"
          role="status"
          className="mb-2 flex items-start gap-1.5 rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-warning"
        >
          <AlertTriangle className="mt-px size-3 shrink-0" />
          <span>
            {hasFetchedData
              ? "Equity history could not be refreshed — the curve below is not current."
              : "Equity history could not be loaded."}{" "}
            {error.detail}
          </span>
        </div>
      )}

      <div
        className={cn(
          "transition-opacity duration-[var(--motion-fast)]",
          fill && "min-h-0 flex-1",
          // Dim on a failed refresh too, not only while loading: the `finally`
          // in useEquitySeries clears `loading` on the failure path, so a dim
          // keyed on loading alone snaps back to full confidence the instant
          // the fetch dies.
          (loading || error !== null) && hasFetchedData && "opacity-60",
        )}
      >
        <EquitySparkline
          points={points}
          series={series}
          height={fill ? "100%" : undefined}
          expanded={fill}
          risk={risk ? { day_anchor: risk.day_anchor, max_daily_dd_pct: risk.max_daily_dd_pct } : undefined}
        />
      </div>
    </div>
  );
}

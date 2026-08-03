import type { RangeName } from "./types";

/** Drawdown severity, keyed to how much of the DAILY loss budget is consumed. */
export type DrawdownSeverity = "shallow" | "moderate" | "severe";

/**
 * Recharts `fill` values per severity. These reference the A2 semantic tokens
 * (`docs/superpowers/specs/2026-08-03-visual-language-foundation-design.md` §6),
 * so a retune moves the chart with the rest of the app. `--dd-severe` is
 * deliberately identical to `--loss`: a deep drawdown and a losing P&L should
 * read as the same red.
 */
export const DD_FILL: Record<DrawdownSeverity, string> = {
  shallow: "hsl(var(--dd-shallow))",
  moderate: "hsl(var(--dd-moderate))",
  severe: "hsl(var(--dd-severe))",
};

/**
 * Severity of a drawdown, as a fraction of the daily loss budget
 * (`dayAnchor * maxDailyDdPct/100`).
 *
 * Keyed to the budget rather than an absolute currency amount because an
 * absolute threshold means nothing across accounts of different size — 20 units
 * is trivial at 100k and fatal at 457.
 *
 * Returns "moderate" whenever severity CANNOT be computed (no anchor yet, no
 * configured breaker, missing drawdown). Guessing "shallow" would tell the
 * operator things are fine on the strength of data we do not have.
 */
export function drawdownSeverity(
  drawdown: number | null,
  dayAnchor: number,
  maxDailyDdPct: number,
): DrawdownSeverity {
  if (drawdown === null || !Number.isFinite(drawdown)) return "moderate";
  if (!Number.isFinite(dayAnchor) || dayAnchor <= 0) return "moderate";
  if (!Number.isFinite(maxDailyDdPct) || maxDailyDdPct <= 0) return "moderate";

  const budget = dayAnchor * (maxDailyDdPct / 100);
  if (budget <= 0) return "moderate";

  const consumed = Math.abs(drawdown) / budget;
  if (consumed < 1 / 3) return "shallow";
  if (consumed <= 2 / 3) return "moderate";
  return "severe";
}

/**
 * Ranges the daily-breaker line may be drawn on.
 *
 * `day_anchor` describes TODAY only and no historical anchors are stored, so on
 * anything longer than a day the line would span periods it never governed.
 */
const INTRADAY_RANGES: ReadonlySet<string> = new Set([
  "15m", "30m", "1h", "4h", "12h", "1d",
]);

export function showsBreakerLine(range: RangeName): boolean {
  return INTRADAY_RANGES.has(range);
}

/** Equity level at which the daily breaker trips. Null when un-computable. */
export function breakerLevel(dayAnchor: number, maxDailyDdPct: number): number | null {
  if (!Number.isFinite(dayAnchor) || dayAnchor <= 0) return null;
  if (!Number.isFinite(maxDailyDdPct) || maxDailyDdPct <= 0) return null;
  return dayAnchor * (1 - maxDailyDdPct / 100);
}

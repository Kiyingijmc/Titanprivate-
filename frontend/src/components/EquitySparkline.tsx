import { Area, AreaChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";
import { toChartRows } from "@/lib/equityChartData";
import type { EquitySeries } from "@/lib/types";

export interface EquityPoint {
  t: number;
  equity: number;
}

// Ranges short enough that a time-of-day tick reads better than a calendar date.
const INTRADAY_RANGES = new Set(["15m", "30m", "1h", "4h", "12h", "1d"]);

function formatTick(ts: number, range: string): string {
  const d = new Date(ts * 1000);
  if (INTRADAY_RANGES.has(range)) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Equity trend as a streaming area chart (dataviz: `--accent` stroke + fading
 * gradient fill, recessive grid, hover tooltip, no entrance animation). The Y
 * domain AUTO-FITS the sampled range (with padding) so small live equity moves
 * are visible instead of a flat line pinned to the top of a 0-based axis. The X
 * axis is UTC epoch seconds, rendered in the viewer's local time. Current value
 * + session delta sit top-right.
 *
 * Two render paths: the legacy `points` prop (a plain live-tail buffer, used by
 * the WS streaming path) and the optional `series` prop (a full API response
 * from `useEquitySeries`, which also draws a balance line, a drawdown area, and
 * breaks the line at real data gaps instead of bridging them — see
 * `toChartRows`). `series` takes precedence when both are given.
 */
export function EquitySparkline({
  points,
  series,
  width = "100%",
  height = 140,
}: {
  points: EquityPoint[];
  series?: EquitySeries;
  width?: number | string;
  height?: number;
}) {
  if (series) {
    return <SeriesChart series={series} width={width} height={height} />;
  }

  if (points.length === 0) {
    return (
      <div
        data-testid="equity-sparkline"
        className="flex items-center justify-center text-sm text-muted-foreground"
        style={{ width: "100%", height }}
      >
        No data yet
      </div>
    );
  }

  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  // Pad the auto-fit domain so the line isn't flush to the panel edges; fall back
  // to a tiny relative pad when the series is flat (min === max).
  const pad = max - min > 0 ? (max - min) * 0.18 : Math.max(1, Math.abs(max) * 0.0015);
  const last = values[values.length - 1];
  const delta = last - values[0];
  const up = delta >= 0;

  return (
    <div
      data-testid="equity-sparkline"
      className="relative"
      style={{ width: "100%", height }}
      role="img"
      aria-label={`Equity trend. Current ${money(last)}, ${up ? "up" : "down"} ${money(Math.abs(delta))} over the last ${points.length} samples.`}
    >
      <div className="pointer-events-none absolute right-1 top-0 z-10 flex items-baseline gap-2" aria-hidden>
        <span className="font-mono tabnum text-sm font-semibold text-foreground">{money(last)}</span>
        <span className={cn("font-mono tabnum text-xs", up ? "text-profit" : "text-loss")}>
          {up ? "+" : ""}
          {money(delta)}
        </span>
      </div>
      <ResponsiveContainer width={width} height={height}>
        <AreaChart data={points} margin={{ top: 22, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.35} />
              <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="hsl(var(--border-strong))" strokeOpacity={0.45} vertical={false} />
          <XAxis dataKey="t" hide />
          <YAxis
            domain={[min - pad, max + pad]}
            stroke="hsl(var(--text-muted))"
            tick={{ fill: "hsl(var(--text-muted))", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={52}
            tickFormatter={(v: number) => Math.round(v).toLocaleString("en-US")}
          />
          <Tooltip
            cursor={{ stroke: "hsl(var(--accent))", strokeOpacity: 0.5, strokeWidth: 1 }}
            contentStyle={{
              background: "hsl(var(--elevated))",
              border: "1px solid hsl(var(--border-strong))",
              borderRadius: 8,
              color: "hsl(var(--foreground))",
              fontSize: 12,
            }}
            labelStyle={{ display: "none" }}
            formatter={(v: number) => [money(v), "Equity"] as [string, string]}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="hsl(var(--accent))"
            strokeWidth={2}
            fill="url(#equity-fill)"
            dot={false}
            isAnimationActive={false}
            activeDot={{ r: 3.5, fill: "hsl(var(--accent))", stroke: "hsl(var(--bg))", strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Render path for the `series` prop — see `EquitySparkline`'s docstring. */
function SeriesChart({
  series,
  width,
  height,
}: {
  series: EquitySeries;
  width: number | string;
  height: number;
}) {
  const rows = toChartRows(series);

  const equityValues = rows.map((r) => r.equity).filter((v): v is number => v !== null);
  const balanceValues = rows.map((r) => r.balance).filter((v): v is number => v !== null);
  const allValues = [...equityValues, ...balanceValues];

  if (allValues.length === 0) {
    const everRecorded = series.coverage.first_sample_ts !== null;
    return (
      <div
        data-testid="equity-sparkline"
        className="flex items-center justify-center text-sm text-muted-foreground"
        style={{ width: "100%", height }}
      >
        {everRecorded ? "No data in this window" : "No data yet"}
      </div>
    );
  }

  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  // Same auto-fit padding rule as the legacy path, but fit over equity AND
  // balance together — otherwise the balance line can sit outside the band.
  const pad = max - min > 0 ? (max - min) * 0.18 : Math.max(1, Math.abs(max) * 0.0015);

  // Drawdown gets its OWN y-axis (id "dd"), never the equity/balance one: on a
  // shared axis a realistic drawdown (tens of units against an equity in the
  // thousands) collapses to a 1-2px sliver pinned to the bottom edge — visible
  // in source, invisible on screen. Domain is [floor, 0] with headroom below
  // the deepest drawdown in the window; when every drawdown is 0 (no losses
  // yet) fall back to a small fixed band so the axis stays well-formed.
  const drawdownValues = rows.map((r) => r.drawdown).filter((v): v is number => v !== null);
  const minDrawdown = drawdownValues.length > 0 ? Math.min(...drawdownValues) : 0;
  const ddFloor = minDrawdown < 0 ? minDrawdown * 1.18 : -1;

  const last = equityValues[equityValues.length - 1] ?? 0;
  const first = equityValues[0] ?? last;
  const delta = last - first;
  const up = delta >= 0;

  return (
    <div
      data-testid="equity-sparkline"
      className="relative"
      style={{ width: "100%", height }}
      role="img"
      aria-label={`Equity trend for the ${series.range} window. Current ${money(last)}, ${up ? "up" : "down"} ${money(Math.abs(delta))}.`}
    >
      <div className="pointer-events-none absolute right-1 top-0 z-10 flex items-baseline gap-2" aria-hidden>
        <span className="font-mono tabnum text-sm font-semibold text-foreground">{money(last)}</span>
        <span className={cn("font-mono tabnum text-xs", up ? "text-profit" : "text-loss")}>
          {up ? "+" : ""}
          {money(delta)}
        </span>
      </div>
      <ResponsiveContainer width={width} height={height}>
        {/* ComposedChart, not AreaChart: recharts' AreaChart only recognizes
            Area as a graphical child, so the balance Line below silently fails
            to render inside it (0 recharts-line nodes in the DOM, no error).
            ComposedChart supports mixing Area/Line/Bar/Scatter and renders
            both series correctly. */}
        <ComposedChart data={rows} margin={{ top: 22, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="equity-series-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.35} />
              <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="hsl(var(--border-strong))" strokeOpacity={0.45} vertical={false} />
          <XAxis
            dataKey="ts"
            type="number"
            domain={["dataMin", "dataMax"]}
            scale="time"
            stroke="hsl(var(--text-muted))"
            tick={{ fill: "hsl(var(--text-muted))", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => formatTick(v, series.range)}
          />
          <YAxis
            yAxisId="equity"
            domain={[min - pad, max + pad]}
            stroke="hsl(var(--text-muted))"
            tick={{ fill: "hsl(var(--text-muted))", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={52}
            tickFormatter={(v: number) => Math.round(v).toLocaleString("en-US")}
          />
          <YAxis yAxisId="dd" hide domain={[ddFloor, 0]} />
          <Tooltip
            cursor={{ stroke: "hsl(var(--accent))", strokeOpacity: 0.5, strokeWidth: 1 }}
            contentStyle={{
              background: "hsl(var(--elevated))",
              border: "1px solid hsl(var(--border-strong))",
              borderRadius: 8,
              color: "hsl(var(--foreground))",
              fontSize: 12,
            }}
            labelFormatter={(v: number) => formatTick(v, series.range)}
            formatter={(v: number, name: string) => [
              money(v),
              name === "equity" ? "Equity" : name === "balance" ? "Balance" : "Drawdown",
            ] as [string, string]}
          />
          <Area
            yAxisId="dd"
            type="monotone"
            dataKey="drawdown"
            stroke="none"
            fill="hsl(var(--loss))"
            fillOpacity={0.18}
            dot={false}
            isAnimationActive={false}
            activeDot={false}
          />
          <Line
            yAxisId="equity"
            type="monotone"
            dataKey="balance"
            stroke="hsl(var(--text-muted))"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
            activeDot={{ r: 3, fill: "hsl(var(--text-muted))", stroke: "hsl(var(--bg))", strokeWidth: 2 }}
          />
          <Area
            yAxisId="equity"
            type="monotone"
            dataKey="equity"
            stroke="hsl(var(--accent))"
            strokeWidth={2}
            fill="url(#equity-series-fill)"
            dot={false}
            isAnimationActive={false}
            activeDot={{ r: 3.5, fill: "hsl(var(--accent))", stroke: "hsl(var(--bg))", strokeWidth: 2 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface EquityPoint {
  t: number;
  equity: number;
}

/**
 * Single-series equity trend as a streaming area chart (dataviz: single series ⇒
 * no legend, one axis, `--accent` stroke + fading gradient fill, recessive grid,
 * hover tooltip, no entrance animation). The Y domain AUTO-FITS the sampled range
 * (with padding) so small live equity moves are visible instead of a flat line
 * pinned to the top of a 0-based axis. The X axis is a monotonic sample index and
 * carries no meaning, so it's hidden. Current value + session delta sit top-right.
 */
export function EquitySparkline({
  points,
  width = "100%",
  height = 140,
}: {
  points: EquityPoint[];
  width?: number | string;
  height?: number;
}) {
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

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface EquityPoint {
  t: number;
  equity: number;
}

/**
 * Single-series equity line chart (dataviz: single series ⇒ no legend, one axis,
 * `--primary` stroke, recessive muted grid/axes, hover tooltip, no entrance animation).
 */
export function EquitySparkline({
  points,
  width = "100%",
  height = 120,
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

  return (
    <div data-testid="equity-sparkline" style={{ width: "100%", height }}>
      <ResponsiveContainer width={width} height={height}>
        <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="hsl(var(--muted-foreground))" strokeOpacity={0.15} vertical={false} />
          <XAxis
            dataKey="t"
            stroke="hsl(var(--muted-foreground))"
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
            tickLine={false}
            axisLine={{ stroke: "hsl(var(--border))" }}
          />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              color: "hsl(var(--foreground))",
            }}
            labelStyle={{ color: "hsl(var(--muted-foreground))" }}
          />
          <Line
            type="monotone"
            dataKey="equity"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

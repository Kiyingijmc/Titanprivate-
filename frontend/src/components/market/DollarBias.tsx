import { DollarSign } from "lucide-react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import type { DollarBias as DollarBiasData } from "@/lib/types";
import { cn } from "@/lib/utils";

const GAUGE_MIN = -100;
const GAUGE_MAX = 100;

function clampPct(bias: number): number {
  const clamped = Math.max(GAUGE_MIN, Math.min(GAUGE_MAX, bias));
  return ((clamped - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100;
}

/** USD strength gauge: -100..+100 bias, a moving trend sparkline, top
 * contributors, and a source badge (LIVE index vs computed). Deliberately
 * uses accent/info (NOT profit/loss) — this is USD strength, not P&L. */
export function DollarBias({ data, className }: { data?: DollarBiasData; className?: string }) {
  if (!data || data.source === "unavailable") {
    return (
      <div
        data-testid="dollar-bias"
        className={cn(
          "flex flex-col gap-2 rounded-lg border border-border bg-surface-1 p-4",
          className
        )}
      >
        <Header source={data?.source} />
        <div
          data-testid="dollar-bias-empty"
          className="flex flex-col items-center justify-center gap-1 rounded-md border border-border bg-surface-2 px-3 py-6 text-center"
        >
          <span className="text-sm text-muted-foreground">Dollar bias unavailable</span>
          <span className="text-xs text-muted-foreground/70">
            No USD price feed is connected yet — populated on demo and backtest data.
          </span>
        </div>
      </div>
    );
  }

  const strong = data.bias >= 0;
  const tone = strong ? "text-accent" : "text-info";
  const gaugePct = clampPct(data.bias);
  const trendPoints = data.trend.map((v, i) => ({ i, v }));
  const topContributors = [...data.contributors]
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, 4);

  return (
    <div
      data-testid="dollar-bias"
      role="img"
      aria-label={`US dollar bias ${data.bias > 0 ? "+" : ""}${data.bias.toFixed(1)} of 100, ${strong ? "USD strong" : "USD weak"}, source ${data.source}.`}
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-4",
        className
      )}
    >
      <Header source={data.source} />

      <div className="flex items-baseline gap-2">
        <span className={cn("font-mono tabnum text-3xl font-semibold leading-none", tone)}>
          {data.bias > 0 ? "+" : ""}
          {data.bias.toFixed(1)}
        </span>
        <span className={cn("text-xs font-medium uppercase tracking-wide", tone)}>
          {strong ? "USD strong" : "USD weak"}
        </span>
        {data.value != null && (
          <span className="ml-auto font-mono tabnum text-xs text-muted-foreground">
            {data.value.toFixed(2)}
          </span>
        )}
      </div>

      <div
        data-testid="dollar-bias-gauge"
        className="relative h-2 w-full rounded-full bg-gradient-to-r from-info/40 via-surface-2 to-accent/40"
      >
        <div
          data-testid="dollar-bias-needle"
          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-foreground bg-background"
          style={{ left: `${gaugePct}%` }}
          aria-hidden
        />
      </div>

      {trendPoints.length > 0 && (
        <div data-testid="dollar-bias-trend" style={{ width: "100%", height: 40 }}>
          <ResponsiveContainer width="100%" height={40}>
            <LineChart data={trendPoints} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
              <Line
                type="monotone"
                dataKey="v"
                stroke={strong ? "hsl(var(--accent))" : "hsl(var(--info))"}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {topContributors.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {topContributors.map((c) => (
            <span
              key={c.symbol}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs"
            >
              <span className="font-mono text-foreground">{c.symbol}</span>
              <span className={cn("font-mono tabnum", c.contribution >= 0 ? "text-accent" : "text-info")}>
                {c.contribution >= 0 ? "+" : ""}
                {c.contribution.toFixed(1)}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Header({ source }: { source?: DollarBiasData["source"] }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h3 className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <DollarSign className="size-3.5" aria-hidden />
        Dollar Bias
      </h3>
      {source === "index" ? (
        <span className="rounded-full border border-accent/40 bg-accent/15 px-2 py-0.5 text-xs font-medium text-accent">
          LIVE index
        </span>
      ) : source === "computed" ? (
        <span className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted-foreground">
          computed
        </span>
      ) : null}
    </div>
  );
}

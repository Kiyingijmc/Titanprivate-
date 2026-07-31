import { RANGE_NAMES, type RangeName } from "@/lib/types";
import { cn } from "@/lib/utils";

const SECONDS: Record<RangeName, number> = {
  "15m": 900, "30m": 1_800, "1h": 3_600, "4h": 14_400, "12h": 43_200,
  "1d": 86_400, "1w": 604_800, "1mo": 2_592_000, "4mo": 10_368_000,
  "6mo": 15_552_000, "1y": 31_536_000,
};

export function rangeSeconds(name: RangeName): number {
  return SECONDS[name];
}

function unlockLabel(firstTs: number, seconds: number): string {
  const when = new Date((firstTs + seconds) * 1000);
  return `Not enough history yet — unlocks ${when.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  })}`;
}

/**
 * Lookback picker for the equity panel.
 *
 * A range is enabled only when the stored series actually reaches back that
 * far (`now - firstSampleTs >= rangeSeconds`). Showing "1Y" over three days of
 * data would draw a year of apparent flatness, which is the same class of quiet
 * lie as a chart that bridges an outage — so the wide ranges stay disabled and
 * say when they unlock.
 *
 * Motion: the only thing that moves is the active pill (transform + opacity,
 * --motion-fast / --ease-out, bound in tailwind.config.ts as duration-fast /
 * ease-out). The chart itself never animates on range change — it is a
 * functional graph switched many times a minute (Task 3's constraint).
 */
export function RangeSelector({
  value,
  onChange,
  firstSampleTs,
  now = Date.now() / 1000,
}: {
  value: RangeName;
  onChange: (r: RangeName) => void;
  firstSampleTs: number | null;
  now?: number;
}) {
  const span = firstSampleTs === null ? 0 : Math.max(0, now - firstSampleTs);
  return (
    <div
      role="radiogroup"
      aria-label="Equity lookback range"
      data-testid="range-selector"
      className="flex flex-wrap items-center gap-0.5 rounded-md bg-elevated p-0.5"
    >
      {RANGE_NAMES.map((name) => {
        const enabled = firstSampleTs !== null && span >= SECONDS[name];
        const active = name === value;
        return (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={!enabled}
            title={
              enabled
                ? undefined
                : firstSampleTs === null
                  ? "No equity history recorded yet"
                  : unlockLabel(firstSampleTs, SECONDS[name])
            }
            onClick={() => enabled && onChange(name)}
            className={cn(
              "rounded px-2 py-1 font-mono text-xs tabnum transition-[transform,opacity] duration-fast ease-out",
              "active:scale-[0.97]",
              active
                ? "bg-accent text-accent-foreground font-semibold"
                : "text-muted-foreground hover:text-foreground",
              !enabled && "cursor-not-allowed opacity-35 hover:text-muted-foreground",
            )}
          >
            {name}
          </button>
        );
      })}
    </div>
  );
}

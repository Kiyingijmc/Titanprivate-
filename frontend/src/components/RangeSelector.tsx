import { useRef } from "react";
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

/** Width of an arbitrary (possibly server-supplied) range string, or null if
 *  it isn't one of ours. Callers outside this module get a string, not a
 *  `RangeName`, and must not index the table blindly. */
export function lookupRangeSeconds(name: string): number | null {
  return Object.prototype.hasOwnProperty.call(SECONDS, name) ? SECONDS[name as RangeName] : null;
}

/**
 * The ranges the stored history actually reaches back far enough to draw, in
 * display order. Shared with the page-level `[` / `]` shortcuts so the keyboard
 * and the mouse can never disagree about what is selectable.
 *
 * `now` MUST be on the SERVER clock (see `useEquitySeries`'s `serverOffset`).
 * Feeding it a raw `Date.now()` compares two clocks: a viewer whose machine is
 * a few minutes slow would compute a negative span, clamp it to 0, and find
 * every range disabled — including the one currently selected.
 */
export function enabledRangeNames(firstSampleTs: number | null, now: number): RangeName[] {
  if (firstSampleTs === null) return [];
  const span = Math.max(0, now - firstSampleTs);
  return RANGE_NAMES.filter((n) => span >= SECONDS[n]);
}

function unlockLabel(firstTs: number, seconds: number): string {
  const when = new Date((firstTs + seconds) * 1000);
  return `Not enough history yet — unlocks ${when.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  })}`;
}

const NAV_KEYS = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];

/**
 * Lookback picker for the equity panel.
 *
 * A range is enabled only when the stored series actually reaches back that
 * far (`now - firstSampleTs >= rangeSeconds`). Showing "1Y" over three days of
 * data would draw a year of apparent flatness, which is the same class of quiet
 * lie as a chart that bridges an outage — so the wide ranges stay disabled and
 * say when they unlock. When `firstSampleTs` is null the tooltip distinguishes
 * "the recorder has nothing" from "we could not reach the recorder"
 * (`loadError`) — the first is a claim about the trading system, the second
 * about the network, and asserting the former from evidence for the latter is
 * exactly the kind of confident wrong statement this panel must not make.
 *
 * Keyboard (WAI-ARIA radiogroup): ONE tab stop, not eleven. Arrow keys and
 * Home/End move between ENABLED options and select as they go; the roving
 * `tabIndex` follows the selection.
 *
 * Motion: the only animated properties are `transform` and `opacity`
 * (--motion-fast / --ease-out, bound in tailwind.config.ts as duration-fast /
 * ease-out), driving the press feedback and the disabled dim. Selection itself
 * is a COLOUR change only and deliberately changes no text metrics — an earlier
 * `font-semibold` on the active pill re-flowed the whole row on every click,
 * which is real layout jank dressed up as a highlight. The chart never animates
 * on range change either — it is a functional graph switched many times a
 * minute (Task 3's constraint).
 */
export function RangeSelector({
  value,
  onChange,
  firstSampleTs,
  loadError = false,
  now = Date.now() / 1000,
}: {
  value: RangeName;
  onChange: (r: RangeName) => void;
  firstSampleTs: number | null;
  loadError?: boolean;
  now?: number;
}) {
  const btnRefs = useRef(new Map<RangeName, HTMLButtonElement | null>());
  const enabledNames = enabledRangeNames(firstSampleTs, now);
  const isEnabled = (n: RangeName) => enabledNames.includes(n);

  // Roving tabindex: exactly one focusable option. Prefer the selected one; if
  // it is (transiently) disabled, hand the tab stop to the first enabled option
  // so the group never becomes unreachable by keyboard.
  const rovingName = isEnabled(value) ? value : enabledNames[0];

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (!NAV_KEYS.includes(e.key) || enabledNames.length === 0) return;
    e.preventDefault();
    const cur = enabledNames.indexOf(value);
    let next: RangeName;
    if (e.key === "Home") {
      next = enabledNames[0];
    } else if (e.key === "End") {
      next = enabledNames[enabledNames.length - 1];
    } else {
      const forward = e.key === "ArrowRight" || e.key === "ArrowDown";
      // A selection outside the enabled set starts from the appropriate edge
      // rather than wrapping off a -1 index.
      const base = cur === -1 ? (forward ? -1 : 0) : cur;
      next = enabledNames[(base + (forward ? 1 : -1) + enabledNames.length) % enabledNames.length];
    }
    if (next !== value) onChange(next);
    btnRefs.current.get(next)?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label="Equity lookback range"
      data-testid="range-selector"
      onKeyDown={handleKeyDown}
      className="flex flex-wrap items-center gap-0.5 rounded-md bg-elevated p-0.5"
    >
      {RANGE_NAMES.map((name) => {
        const enabled = isEnabled(name);
        const active = name === value;
        return (
          <button
            key={name}
            ref={(el) => { btnRefs.current.set(name, el); }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={name === rovingName ? 0 : -1}
            disabled={!enabled}
            title={
              enabled
                ? undefined
                : firstSampleTs === null
                  ? loadError
                    ? "Could not load equity history — the range is unavailable until the series loads"
                    : "No equity history recorded yet"
                  : unlockLabel(firstSampleTs, SECONDS[name])
            }
            onClick={() => enabled && onChange(name)}
            className={cn(
              "rounded px-2 py-1 font-mono text-xs tabnum transition-[transform,opacity] duration-fast ease-out",
              "active:scale-[0.97]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "bg-accent text-accent-foreground"
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

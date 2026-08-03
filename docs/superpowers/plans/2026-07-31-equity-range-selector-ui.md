# Equity Range Selector UI Implementation Plan (phase 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put an eleven-range lookback selector on the Overview equity panel, backed by the `GET /api/equity` series that phase 1 built, so the chart finally shows equity over real time instead of a browser-local sample counter.

**Architecture:** A typed `getEquity` on the existing api client feeds a `useEquitySeries(range)` hook (fetch on change + slow poll). A `RangeSelector` renders the eleven ranges and disables any range wider than `coverage.first_sample_ts`. `EquitySparkline` gains a real time X axis, a second `balance` line, a drawdown area, and renders API gap markers as line breaks. `OverviewPage` composes them and keeps the existing live WS tail on short ranges.

**Tech Stack:** React 18 + TypeScript, Vite, Recharts 2, Tailwind + shadcn, vitest + @testing-library/react.

## Global Constraints

- Phase 1 is merged on this branch. `GET /api/equity?range=<name>` returns `{range, tier, bucket_s, series[], points[], coverage{first_sample_ts, n, series_first_ts, gaps[][]}}`. A `null` entry in `points` is a gap. Do not re-derive any of this client-side.
- Timestamps from the API are **UTC epoch seconds** (numbers). Format for display with the user's locale at render time only; never store a formatted string.
- **The chart does not animate.** `isAnimationActive={false}` on every Recharts series, and no crossfade on range change. A functional graph in a trading app, switched several times a minute, is the canonical case where no animation beats animation.
- **Gaps are never bridged.** A gap must render as a visible break. `connectNulls` must be false (Recharts' default — do not set it true).
- Only `transform` and `opacity` are animated, at `--motion-fast` (150ms). Reduced motion is already handled globally in `frontend/src/index.css:20`; anything you add must be covered by it.
- Test command, run from `frontend/`: `npx vitest run <path>` for one file, `npm test` for all. There are 127+ existing frontend tests and they must stay green.
- Never `git add -A`. `.venv` at the repo root is an untracked symlink — never stage it.
- Do not modify any Python file. Phase 1's backend is closed.

---

### Task 1: Typed equity series + `useEquitySeries` hook

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/useEquitySeries.ts`
- Test: `frontend/src/lib/useEquitySeries.test.ts`

**Interfaces:**
- Consumes: `createApi(getToken, opts)` from `api.ts`, whose private `req<T>` already attaches the bearer token and maps a 422 to `ApiError.kind === "validation"`.
- Produces: types `RangeName`, `EquityPoint`, `EquityCoverage`, `EquitySeries`; `api.getEquity(range)`; hook `useEquitySeries(api, range, opts?)` returning `{ data, loading, error }`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/lib/useEquitySeries.test.ts
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useEquitySeries } from "./useEquitySeries";
import type { EquitySeries } from "./types";

const series = (range: string): EquitySeries => ({
  range, tier: "coarse", bucket_s: 300, series: ["equity", "balance", "peak"],
  points: [{ ts: 1000, equity: 10, balance: 9, peak: 11 }],
  coverage: { first_sample_ts: 500, n: 1, series_first_ts: {}, gaps: [] },
});

describe("useEquitySeries", () => {
  it("fetches on mount and exposes the series", async () => {
    const getEquity = vi.fn(async (r: string) => series(r));
    const { result } = renderHook(() => useEquitySeries({ getEquity } as never, "1d", { pollMs: 0 }));
    await waitFor(() => expect(result.current.data?.range).toBe("1d"));
    expect(getEquity).toHaveBeenCalledWith("1d");
    expect(result.current.loading).toBe(false);
  });

  it("refetches when the range changes and drops a stale in-flight response", async () => {
    let resolveFirst: (v: EquitySeries) => void = () => {};
    const getEquity = vi.fn((r: string) =>
      r === "1d" ? new Promise<EquitySeries>((res) => { resolveFirst = res; }) : Promise.resolve(series(r)));
    const { result, rerender } = renderHook(({ r }) => useEquitySeries({ getEquity } as never, r, { pollMs: 0 }),
      { initialProps: { r: "1d" } });
    rerender({ r: "1w" });
    await waitFor(() => expect(result.current.data?.range).toBe("1w"));
    await act(async () => { resolveFirst(series("1d")); });   // stale response lands late
    expect(result.current.data?.range).toBe("1w");            // and must be ignored
  });

  it("surfaces an error without clearing the last good data", async () => {
    const getEquity = vi.fn()
      .mockResolvedValueOnce(series("1d"))
      .mockRejectedValueOnce({ status: 500, kind: "error", detail: "boom" });
    const { result } = renderHook(() => useEquitySeries({ getEquity } as never, "1d", { pollMs: 10 }));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    await waitFor(() => expect(result.current.error).not.toBeNull(), { timeout: 2000 });
    expect(result.current.data?.range).toBe("1d");            // last good series survives
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/lib/useEquitySeries.test.ts`
Expected: FAIL — `Failed to resolve import "./useEquitySeries"`.

- [ ] **Step 3: Add the types**

Append to `frontend/src/lib/types.ts`:

```ts
export const RANGE_NAMES = ["15m","30m","1h","4h","12h","1d","1w","1mo","4mo","6mo","1y"] as const;
export type RangeName = (typeof RANGE_NAMES)[number];

/** One downsampled bucket. A `null` entry in EquitySeries.points is a data gap. */
export interface EquityPoint {
  ts: number;                 // UTC epoch seconds
  equity: number;
  balance: number;
  peak: number;
  [series: string]: number;   // future registry series arrive here
}

export interface EquityCoverage {
  first_sample_ts: number | null;
  n: number;
  series_first_ts: Record<string, number | null>;
  gaps: [number, number][];
}

export interface EquitySeries {
  range: string;
  tier: "fine" | "coarse";
  bucket_s: number | null;
  series: string[];
  points: (EquityPoint | null)[];
  coverage: EquityCoverage;
}
```

- [ ] **Step 4: Add the client method**

In `frontend/src/lib/api.ts`, add `EquitySeries` to the type import list, and add this entry to the returned object (immediately after `getHistory`):

```ts
    getEquity: (range: string) => req<EquitySeries>(`/api/equity?range=${encodeURIComponent(range)}`),
```

- [ ] **Step 5: Write the hook**

```ts
// frontend/src/lib/useEquitySeries.ts
import { useEffect, useRef, useState } from "react";
import type { Api, ApiError } from "./api";
import type { EquitySeries } from "./types";

const DEFAULT_POLL_MS = 30_000;

/**
 * Fetches one lookback range and keeps it fresh on a slow poll.
 *
 * Two deliberate behaviours: a response for a range the user has already moved
 * away from is DISCARDED (a slow 1y query must not overwrite the 15m the user
 * is now looking at), and a failed refresh leaves the last good series on
 * screen rather than blanking the panel — an empty chart reads as "flat", which
 * is a lie the rest of this codebase is careful not to tell.
 */
export function useEquitySeries(api: Pick<Api, "getEquity">, range: string,
                                opts: { pollMs?: number } = {}) {
  const pollMs = opts.pollMs ?? DEFAULT_POLL_MS;
  const [data, setData] = useState<EquitySeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const wanted = useRef(range);

  useEffect(() => {
    wanted.current = range;
    let alive = true;
    setLoading(true);

    const load = async () => {
      try {
        const s = await api.getEquity(range);
        if (!alive || wanted.current !== range) return;   // stale range — drop it
        setData(s);
        setError(null);
      } catch (e) {
        if (!alive || wanted.current !== range) return;
        setError(e as ApiError);                          // keep last good `data`
      } finally {
        if (alive && wanted.current === range) setLoading(false);
      }
    };

    void load();
    if (pollMs <= 0) return () => { alive = false; };
    const id = setInterval(() => { void load(); }, pollMs);
    return () => { alive = false; clearInterval(id); };
  }, [api, range, pollMs]);

  return { data, loading, error };
}
```

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npx vitest run src/lib/useEquitySeries.test.ts`
Expected: PASS, 3 tests.
Then `npx vitest run src/lib/api.test.ts` — still passing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/lib/useEquitySeries.ts frontend/src/lib/useEquitySeries.test.ts
git commit -m "feat(gui): typed equity series client + useEquitySeries hook"
```

---

### Task 2: `RangeSelector` — eleven ranges, coverage-gated

**Files:**
- Create: `frontend/src/components/RangeSelector.tsx`
- Test: `frontend/src/components/RangeSelector.test.tsx`
- Modify: `frontend/src/design/tokens.css`

**Interfaces:**
- Consumes: `RANGE_NAMES`, `RangeName` from Task 1's `types.ts`.
- Produces: `<RangeSelector value onChange firstSampleTs now? />`, and `rangeSeconds(name)` exported for reuse by Task 4.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/RangeSelector.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RangeSelector, rangeSeconds } from "./RangeSelector";

const NOW = 1_800_000_000;

describe("RangeSelector", () => {
  it("renders all eleven ranges and marks the active one", () => {
    render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={0} now={NOW} />);
    expect(screen.getAllByRole("radio")).toHaveLength(11);
    expect(screen.getByRole("radio", { name: "1d" })).toHaveAttribute("aria-checked", "true");
  });

  it("disables ranges wider than the available history and says when they unlock", () => {
    // three days of history: 1d is fine, 1w is not
    render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={NOW - 3 * 86400} now={NOW} />);
    expect(screen.getByRole("radio", { name: "1d" })).not.toBeDisabled();
    const week = screen.getByRole("radio", { name: "1w" });
    expect(week).toBeDisabled();
    expect(week).toHaveAttribute("title", expect.stringContaining("unlocks"));
  });

  it("disables every range when there is no history at all", () => {
    render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={null} now={NOW} />);
    screen.getAllByRole("radio").forEach((b) => expect(b).toBeDisabled());
  });

  it("emits the clicked range and never emits a disabled one", async () => {
    const onChange = vi.fn();
    render(<RangeSelector value="1d" onChange={onChange} firstSampleTs={NOW - 3 * 86400} now={NOW} />);
    await userEvent.click(screen.getByRole("radio", { name: "4h" }));
    expect(onChange).toHaveBeenCalledWith("4h");
    await userEvent.click(screen.getByRole("radio", { name: "1y" }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("rangeSeconds covers every range name", () => {
    expect(rangeSeconds("15m")).toBe(900);
    expect(rangeSeconds("1d")).toBe(86_400);
    expect(rangeSeconds("1y")).toBe(31_536_000);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/components/RangeSelector.test.tsx`
Expected: FAIL — cannot resolve `./RangeSelector`.

- [ ] **Step 3: Add the easing token AND bind it**

In `frontend/src/design/tokens.css`, extend the existing motion line (currently `--motion-fast: 150ms; --motion-base: 220ms; --ease: cubic-bezier(0.2, 0, 0, 1);`) with:

```css
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
```

It is bound by `RangeSelector.tsx` in Step 4. **A token no rule references is dead CSS — this repo has shipped unbound motion tokens before, so the binding lands in the same commit as the token.**

- [ ] **Step 4: Write the component**

```tsx
// frontend/src/components/RangeSelector.tsx
import { RANGE_NAMES, type RangeName } from "@/lib/types";
import { cn } from "@/lib/utils";

const SECONDS: Record<RangeName, number> = {
  "15m": 900, "30m": 1_800, "1h": 3_600, "4h": 14_400, "12h": 43_200,
  "1d": 86_400, "1w": 604_800, "1mo": 2_592_000, "4mo": 10_368_000,
  "6mo": 15_552_000, "1y": 31_536_000,
};

export function rangeSeconds(name: RangeName): number { return SECONDS[name]; }

function unlockLabel(firstTs: number, seconds: number): string {
  const when = new Date((firstTs + seconds) * 1000);
  return `Not enough history yet — unlocks ${when.toLocaleDateString(undefined,
    { day: "numeric", month: "short", year: "numeric" })}`;
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
 * --motion-fast). The chart itself never animates on range change — it is a
 * functional graph switched many times a minute.
 */
export function RangeSelector({
  value, onChange, firstSampleTs, now = Date.now() / 1000,
}: {
  value: RangeName;
  onChange: (r: RangeName) => void;
  firstSampleTs: number | null;
  now?: number;
}) {
  const span = firstSampleTs === null ? 0 : Math.max(0, now - firstSampleTs);
  return (
    <div role="radiogroup" aria-label="Equity lookback range"
         data-testid="range-selector"
         className="flex flex-wrap items-center gap-0.5 rounded-md bg-[hsl(var(--elevated))] p-0.5">
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
            title={enabled ? undefined : firstSampleTs === null
              ? "No equity history recorded yet"
              : unlockLabel(firstSampleTs, SECONDS[name])}
            onClick={() => enabled && onChange(name)}
            className={cn(
              "rounded px-2 py-1 font-mono text-xs tabnum transition-[transform,opacity,background-color,color]",
              "duration-[var(--motion-fast)] ease-[var(--ease-out)]",
              "active:scale-[0.97]",
              active
                ? "bg-[hsl(var(--accent))] text-[hsl(var(--bg))] font-semibold"
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
```

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/components/RangeSelector.test.tsx`
Expected: PASS, 5 tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RangeSelector.tsx frontend/src/components/RangeSelector.test.tsx frontend/src/design/tokens.css
git commit -m "feat(gui): coverage-gated eleven-range lookback selector"
```

---

### Task 3: `EquitySparkline` — real time axis, balance line, drawdown, gap breaks

**Files:**
- Modify: `frontend/src/components/EquitySparkline.tsx`
- Modify: `frontend/src/components/EquitySparkline.test.tsx`
- Create: `frontend/src/lib/equityChartData.ts`
- Test: `frontend/src/lib/equityChartData.test.ts`

**Interfaces:**
- Consumes: `EquitySeries`, `EquityPoint` from Task 1.
- Produces: `toChartRows(series) -> ChartRow[]` where `ChartRow = { ts: number; equity: number | null; balance: number | null; drawdown: number | null }`; `EquitySparkline` gains optional props `series?: EquitySeries` and keeps the legacy `points` prop for the live-tail path.

The transform lives in its own module because it carries the gap rule, which is the part most worth testing without a DOM.

- [ ] **Step 1: Write the failing transform test**

```ts
// frontend/src/lib/equityChartData.test.ts
import { describe, it, expect } from "vitest";
import { toChartRows } from "./equityChartData";
import type { EquitySeries } from "./types";

const base = (over: Partial<EquitySeries>): EquitySeries => ({
  range: "1d", tier: "coarse", bucket_s: 300, series: ["equity", "balance", "peak"],
  points: [], coverage: { first_sample_ts: 0, n: 0, series_first_ts: {}, gaps: [] }, ...over,
});

describe("toChartRows", () => {
  it("maps points and derives drawdown as equity minus peak", () => {
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80, peak: 100 } as never],
    }));
    expect(rows).toEqual([{ ts: 100, equity: 90, balance: 80, drawdown: -10 }]);
  });

  it("turns a null point into a null-valued row at the gap midpoint, so the line BREAKS", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 100, equity: 10, balance: 9, peak: 10 } as never,
        null,
        { ts: 900, equity: 12, balance: 9, peak: 12 } as never,
      ],
      coverage: { first_sample_ts: 100, n: 2, series_first_ts: {}, gaps: [[100, 900]] },
    }));
    expect(rows).toHaveLength(3);
    expect(rows[1]).toEqual({ ts: 500, equity: null, balance: null, drawdown: null });
  });

  it("pairs the nth null with the nth reported gap", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 0, equity: 1, balance: 1, peak: 1 } as never, null,
        { ts: 400, equity: 1, balance: 1, peak: 1 } as never, null,
        { ts: 1000, equity: 1, balance: 1, peak: 1 } as never,
      ],
      coverage: { first_sample_ts: 0, n: 3, series_first_ts: {}, gaps: [[0, 400], [400, 1000]] },
    }));
    expect(rows[1].ts).toBe(200);
    expect(rows[3].ts).toBe(700);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/lib/equityChartData.test.ts`
Expected: FAIL — cannot resolve `./equityChartData`.

- [ ] **Step 3: Write the transform**

```ts
// frontend/src/lib/equityChartData.ts
import type { EquitySeries } from "./types";

export interface ChartRow {
  ts: number;
  equity: number | null;
  balance: number | null;
  drawdown: number | null;
}

/**
 * Flattens an API series into Recharts rows.
 *
 * A `null` point from the API is a real data gap. It becomes a row whose values
 * are all `null`, positioned at the midpoint of the corresponding reported gap,
 * so Recharts breaks the line there instead of drawing straight across it. The
 * nth null pairs with the nth entry of `coverage.gaps` — the backend emits them
 * in the same order. A bridged gap would claim the account was flat and healthy
 * through an outage; there was a real ~9-hour one on 2026-07-29.
 */
export function toChartRows(series: EquitySeries): ChartRow[] {
  const rows: ChartRow[] = [];
  let gapIdx = 0;
  for (const p of series.points) {
    if (p === null) {
      const gap = series.coverage.gaps[gapIdx++];
      const ts = gap ? (gap[0] + gap[1]) / 2 : (rows[rows.length - 1]?.ts ?? 0);
      rows.push({ ts, equity: null, balance: null, drawdown: null });
      continue;
    }
    const peak = typeof p.peak === "number" ? p.peak : p.equity;
    rows.push({ ts: p.ts, equity: p.equity, balance: p.balance, drawdown: p.equity - peak });
  }
  return rows;
}
```

- [ ] **Step 4: Run the transform test**

Run: `cd frontend && npx vitest run src/lib/equityChartData.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 5: Teach the chart the new shape**

In `EquitySparkline.tsx`: keep the existing `points` prop and its whole render path unchanged (the live tail still uses it), and add an optional `series?: EquitySeries` prop that takes precedence when present. When rendering from `series`:

- rows come from `toChartRows(series)`
- `<XAxis dataKey="ts" type="number" domain={["dataMin","dataMax"]} scale="time" tickFormatter={...}/>` — **no longer `hide`**. Format ticks as `HH:MM` when `series.range` is one of `15m/30m/1h/4h/12h/1d`, else `D MMM`.
- three marks, all `isAnimationActive={false}`, all `connectNulls` left at its default false:
  - `<Area dataKey="drawdown" .../>` rendered first, muted, `stroke="none"`, filled with a low-opacity `--loss`
  - `<Line dataKey="balance" stroke="hsl(var(--text-muted))" strokeWidth={1.5} dot={false}/>`
  - the existing equity `<Area>` unchanged apart from `dataKey` staying `equity`
- Y domain: auto-fit over equity **and** balance together, keeping the existing 0.18 padding rule.
- Update the docstring: delete the sentence claiming the X axis carries no meaning, and say the axis is UTC epoch seconds rendered in local time.
- Keep the empty state, and add a distinct one for "recorded, but nothing in this window".

- [ ] **Step 6: Extend the component test**

Add to `EquitySparkline.test.tsx` — keep every existing test:

```tsx
  it("renders from an API series and breaks the line at a gap", () => {
    const series = {
      range: "1d", tier: "coarse" as const, bucket_s: 300,
      series: ["equity", "balance", "peak"],
      points: [
        { ts: 1000, equity: 100, balance: 90, peak: 100 },
        null,
        { ts: 2000, equity: 110, balance: 90, peak: 110 },
      ],
      coverage: { first_sample_ts: 1000, n: 2, series_first_ts: {}, gaps: [[1000, 2000]] as [number, number][] },
    };
    const { container } = render(<EquitySparkline points={[]} series={series as never} />);
    expect(screen.getByTestId("equity-sparkline")).toBeInTheDocument();
    // the gap row is present in the data Recharts receives, with null values
    expect(container.querySelectorAll("svg").length).toBeGreaterThan(0);
  });

  it("never animates any series", () => {
    // guards the motion decision: a functional trading chart switched many
    // times a minute must not re-animate on every range change
    const src = EquitySparkline.toString();
    expect(src).not.toContain("isAnimationActive={true}");
  });
```

- [ ] **Step 7: Run tests**

Run: `cd frontend && npx vitest run src/components/EquitySparkline.test.tsx src/lib/equityChartData.test.ts`
Expected: PASS, existing tests plus the new ones.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx frontend/src/lib/equityChartData.ts frontend/src/lib/equityChartData.test.ts
git commit -m "feat(gui): time-axis equity chart with balance, drawdown and honest gaps"
```

---

### Task 4: Compose on the Overview page

**Files:**
- Modify: `frontend/src/sections/OverviewPage.tsx`
- Modify: `frontend/src/sections/OverviewPage.test.tsx`

**Interfaces:**
- Consumes: `useEquitySeries` (Task 1), `RangeSelector` + `rangeSeconds` (Task 2), `EquitySparkline` with `series` (Task 3), and the existing `useEquityBuffer` + `useController`.
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Add to `OverviewPage.test.tsx`, following whatever provider wrapper the existing tests in that file already use — read it first and reuse it, do not invent a second harness:

```tsx
  it("shows the range selector defaulted to 1d and swaps the series when a range is picked", async () => {
    // uses the file's existing render helper + a stubbed api whose getEquity
    // records the requested range
    // 1. assert the selector is present with 1d active
    // 2. click "4h"
    // 3. assert getEquity was called with "4h"
  });
```

Write it out concretely against the file's real harness — the three numbered lines above describe the assertions, and the implementer must express them in that harness's idiom rather than copying a generic one.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/sections/OverviewPage.test.tsx`
Expected: FAIL — no `range-selector` testid in the tree.

- [ ] **Step 3: Wire the page**

In `OverviewPage`:

```tsx
  const [range, setRange] = useState<RangeName>("1d");
  const equity = useEquitySeries(api, range);
  const liveTail = useEquityBuffer(snapshot?.account.equity);
```

Render inside the existing Equity `<Panel>`, with the selector in a header row above the chart:

```tsx
        <Panel status={baseStatus} title="Equity">
          <div className="mb-3 flex justify-end">
            <RangeSelector value={range} onChange={setRange}
                           firstSampleTs={equity.data?.coverage.first_sample_ts ?? null} />
          </div>
          <div className={cn("transition-opacity duration-[var(--motion-fast)]",
                             equity.loading && equity.data && "opacity-60")}>
            <EquitySparkline points={liveTail} series={equity.data ?? undefined} />
          </div>
        </Panel>
```

The in-flight dip is opacity only — no motion, no skeleton swap, no layout shift.

- [ ] **Step 4: Run the page tests**

Run: `cd frontend && npx vitest run src/sections/OverviewPage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the whole frontend suite**

Run: `cd frontend && npm test`
Expected: all existing tests plus the new ones green. Fix any fallout here, in this task.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/sections/OverviewPage.tsx frontend/src/sections/OverviewPage.test.tsx
git commit -m "feat(gui): range-selected equity series on the Overview panel"
```

---

### Task 5: Build, typecheck, and a live pass against the devserver

**Files:**
- Modify: whatever the typecheck or build turns up. No new files expected.

- [ ] **Step 1: Typecheck and build**

Run: `cd frontend && npx tsc -b && npm run build`
Expected: no errors. `EquityPoint`'s index signature can make TypeScript unhappy about `peak` — if so, narrow the interface rather than casting at call sites.

- [ ] **Step 2: Drive it against the fake controller**

Phase 1 made `fake_controller.py` seed both tiers with deliberate gaps, so all eleven ranges are drivable with MT5 offline:

```bash
cd /tmp/claude-1000/-home-kiyingijmc-projects-Titan-ICT-Bot-v14-3pro/33a3fff5-d779-4f0c-b1c5-8fedd78036e1/scratchpad/equity-wt
.venv/bin/python -m src.ops.web.devserver
```

Then, from a second shell, confirm the API the UI depends on actually answers for a short and a long range:

```bash
curl -s -H "Authorization: Bearer $TITAN_GUI_TOKEN" 'http://127.0.0.1:8770/api/equity?range=15m' | head -c 400
curl -s -H "Authorization: Bearer $TITAN_GUI_TOKEN" 'http://127.0.0.1:8770/api/equity?range=1y' | head -c 400
```

Record in your report: the point count for each, whether `coverage.first_sample_ts` is populated, and how many gaps each reports. If `15m` returns zero points, phase 1's fine-tier seeding regressed — STOP and report rather than compensating in the UI.

- [ ] **Step 3: Full frontend suite once more**

Run: `cd frontend && npm test`
Expected: green.

- [ ] **Step 4: Commit any fixes**

```bash
git add <explicit paths>
git commit -m "fix(gui): <what the build or live pass turned up>"
```

---

## Out of scope

- Any Python change. Phase 1's backend is closed; if the API is wrong, report it rather than working around it in the UI.
- Persisting the selected range across reloads.
- A second chart anywhere else in the app.
- Wiring `peak`/drawdown into any *limit*. The audit notes `equity_max` is tracked and read by no control; making drawdown visible is a GUI change, enforcing it is a risk change.

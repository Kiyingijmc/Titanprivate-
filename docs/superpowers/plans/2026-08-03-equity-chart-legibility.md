# Equity Chart Legibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the equity panel readable — name every series with a legend, draw the high-water mark, give drawdown a severity ramp that means something, and add a daily-breaker reference that is only drawn where it is true.

**Architecture:** Two tiny pure functions (severity ramp, breaker-visibility predicate) land in a new `equityChartPolicy.ts` and are unit-tested in isolation; `peak` is threaded onto `ChartRow`; then `EquitySparkline` grows an `expanded` mode that splits drawdown into its own underwater pane beneath the equity plot, sharing the x-axis. The collapsed 140px card keeps today's single-pane layout.

**Tech Stack:** React 18, TypeScript, Recharts (`ComposedChart`), Tailwind 3, Vitest + Testing Library.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-equity-chart-legibility-design.md`. Read it before starting.
- Working directory for every command is `frontend/`. Put Node on PATH first: `export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"`.
- Run one test file with `npx vitest run <path>`; everything with `npm test`; type-check with `npx tsc -b`; build with `npm run build`.
- `node_modules` already exists. Do NOT run `npm install` / `npm ci`.
- tsconfig has `noUnusedLocals: true` / `noUnusedParameters: true` — unused imports are build errors.
- **No test may assert a Tailwind class string, a hex, an HSL literal, or a rendered colour.** jsdom computes no layout and resolves no colour. Ask of every guard: *what mutation makes this red?*
- **This is frontend-only.** No Python, no backend, no bot restart. `peak` is already served by the API and already reaches the frontend.
- **The single-instance invariant binds:** only ONE chart is mounted at a time. `getByTestId` throws on multiple matches, so a duplicated `equity-sparkline` breaks unrelated existing tests and doubles live chart work every heartbeat. The underwater pane is a second *chart element inside the same component*, never a second mounted `EquitySparkline`.
- **Do not weaken the `equity - peak` guard** in `equityChartData.ts:52-58`. A bucket null for equity but numeric for peak must not fabricate a full-equity drawdown.
- `--dd-severe` is byte-identical to `--loss`. That is deliberate (A2 spec §6) — do not "fix" it.
- The live trading bot serves `frontend/dist` from the main checkout. Work in the worktree you are given; do not rebuild `dist` in the main checkout and do not restart anything. Never bind ports 8770 / 32768 / 32769.
- Commit after every task.

---

## Shared test fixtures (read before Task 3)

`frontend/src/components/EquitySparkline.test.tsx` has **no** series factory today — its existing
tests build series inline. Tasks 3-8 need two, so add them **once**, at the top of that file below
the imports, when you reach Task 3:

```tsx
import type { EquitySeries, RangeName } from "@/lib/types";

/** A minimal well-formed series. `peak === equity`, so drawdown is flat 0. */
function makeSeries(range: RangeName = "1d"): EquitySeries {
  return {
    range, tier: "coarse", bucket_s: 300,
    series: ["equity", "balance", "peak"],
    points: [
      { ts: 1000, equity: 1000, balance: 1000, peak: 1000 },
      { ts: 2000, equity: 1000, balance: 1000, peak: 1000 },
    ],
    coverage: { first_sample_ts: 1000, n: 2, series_first_ts: {}, gaps: [] },
  } as unknown as EquitySeries;
}

/** A series whose deepest point sits `depth` below the high-water mark.
 *  `depth` is NEGATIVE (drawdown = equity - peak). */
function makeSeriesWithDrawdown(depth: number, range: RangeName = "1d"): EquitySeries {
  const peak = 1000;
  return {
    range, tier: "coarse", bucket_s: 300,
    series: ["equity", "balance", "peak"],
    points: [
      { ts: 1000, equity: peak, balance: peak, peak },
      { ts: 2000, equity: peak + depth, balance: peak, peak },
      { ts: 3000, equity: peak + depth / 2, balance: peak, peak },
    ],
    coverage: { first_sample_ts: 1000, n: 3, series_first_ts: {}, gaps: [] },
  } as unknown as EquitySeries;
}
```

🔴 **Every test that asserts on rendered SVG MUST pass explicit pixel dimensions:**
`render(<EquitySparkline points={[]} series={makeSeries()} width={400} height={200} />)`.

jsdom does no layout, so Recharts' `<ResponsiveContainer>` measures 0×0 at the default `width="100%"`
and mounts **no SVG at all** — every `.recharts-area` / `.recharts-line` / tick query then returns
empty and the assertion either fails confusingly or passes vacuously. `EquitySparkline` already
accepts `width` and `height` props for exactly this reason, and the existing gap test in that file
documents it. The tests below pass them; do not drop them.

For expanded-mode tests, pass `width={400} height={400}` — the underwater pane takes 26% of the
height, so a 200px total leaves it too short to mount reliably.

---

### Task 1: `peak` reaches ChartRow

**Files:**
- Modify: `frontend/src/lib/equityChartData.ts`
- Test: `frontend/src/lib/equityChartData.test.ts` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ChartRow` gains `peak: number | null`. Tasks 4 and 5 read `row.peak`.

`peak` is already fetched and already reaching this function — `equityChartData.ts:87` reads it to derive `drawdown` and then discards it. This task keeps it.

⚠️ Line 87 currently reads `const peak = finiteOrNull(p.peak) ?? equity;`. That `?? equity` fallback exists so drawdown is `0` (not `null`) when the backend omits `peak`. **Keep that behaviour for `drawdown`, but do NOT emit the fallback as `peak`** — a row whose `peak` was never reported must not claim the high-water mark equalled equity, or Task 4 draws a fabricated staircase exactly on top of the equity line.

- [ ] **Step 1: Write the failing test**

That file already has a `base(over: Partial<EquitySeries>)` helper at the top — use it rather than writing a new fixture. Append:

```ts
describe("peak on ChartRow (B1 spec §5)", () => {
  it("carries a reported peak through as a real number", () => {
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80, peak: 120 } as never],
    }));
    expect(rows[0].peak).toBe(120);
  });

  it("leaves peak null when the backend omitted it, instead of echoing equity", () => {
    // The `?? equity` fallback may keep drawdown at 0, but peak itself must stay
    // null — otherwise the high-water line is drawn on top of the equity line
    // and reads as a real, flat high-water mark that was never recorded.
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80 } as never],
    }));
    expect(rows[0].peak).toBeNull();
    expect(rows[0].drawdown).toBe(0);
  });

  it("leaves peak null on a declared gap row", () => {
    const rows = toChartRows(base({
      points: [
        { ts: 100, equity: 90, balance: 80, peak: 120 } as never,
        null as never,
        { ts: 300, equity: 90, balance: 80, peak: 120 } as never,
      ],
      coverage: { first_sample_ts: 100, n: 2, series_first_ts: {}, gaps: [[100, 300]] as [number, number][] },
    }));
    const gapRow = rows.find((r) => r.equity === null);
    expect(gapRow).toBeDefined();
    expect(gapRow!.peak).toBeNull();
  });

  it("leaves peak null when the reported value is not finite", () => {
    const rows = toChartRows(base({
      points: [{ ts: 100, equity: 90, balance: 80, peak: Number.NaN } as never],
    }));
    expect(rows[0].peak).toBeNull();
  });
});
```

🔴 **This task WILL break four existing assertions in the same file**, and that is expected, not a
regression. `equityChartData.test.ts` asserts whole rows with `toEqual`, so a new `ChartRow` field
makes them fail:

- `:15` — `expect(rows).toEqual([{ ts: 100, equity: 90, balance: 80, drawdown: -10 }])`
- `:28` — `expect(rows[1]).toEqual({ ts: 500, equity: null, balance: null, drawdown: null })`
- `:120-121` — two rows in a `toEqual` array

Update each by adding the correct `peak` value (`100`, `null`, and whatever the fixture reports).
**Do not** switch them to `toMatchObject` to dodge the failure — the exactness is the point: it is
what catches an unintended extra field appearing on a chart row.

- [ ] **Step 2: Run test to verify it fails**

```bash
export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"
cd frontend && npx vitest run src/lib/equityChartData.test.ts
```

Expected: FAIL — `rows[0].peak` is `undefined`, because `ChartRow` has no `peak` field.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/lib/equityChartData.ts`, add to the `ChartRow` interface:

```ts
export interface ChartRow {
  ts: number;
  equity: number | null;
  balance: number | null;
  drawdown: number | null;
  /** High-water mark as REPORTED. Null when the backend omitted it — never
   *  echoes equity, or the high-water line becomes a fabricated flat staircase
   *  sitting exactly on the equity curve. */
  peak: number | null;
}
```

In the gap-row push (currently `rows.push({ ts, equity: null, balance: null, drawdown: null });`):

```ts
      rows.push({ ts, equity: null, balance: null, drawdown: null, peak: null });
```

In the real-point branch, replace the two lines computing `peak`/`drawdown` and the push:

```ts
    const reportedPeak = finiteOrNull(p.peak);
    // `?? equity` keeps drawdown at 0 when peak was not reported; the reported
    // value alone is what leaves this function as `peak`.
    const peakForDrawdown = reportedPeak ?? equity;
    const drawdown = equity !== null && peakForDrawdown !== null ? equity - peakForDrawdown : null;
    rows.push({ ts, equity, balance, drawdown, peak: reportedPeak });
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/lib/equityChartData.test.ts && npx tsc -b
```

Expected: PASS, clean type-check. `tsc` will flag any other construction site of `ChartRow` that now misses `peak` — fix those by adding `peak: null`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/equityChartData.ts frontend/src/lib/equityChartData.test.ts
git commit -m "feat(equity): carry the reported high-water mark onto ChartRow"
```

---

### Task 2: Chart policy — severity ramp and breaker visibility

**Files:**
- Create: `frontend/src/lib/equityChartPolicy.ts`
- Test: `frontend/src/lib/equityChartPolicy.test.ts`

**Interfaces:**
- Consumes: `RangeName` from `@/lib/types`.
- Produces:
  - `type DrawdownSeverity = "shallow" | "moderate" | "severe"`
  - `drawdownSeverity(drawdown: number | null, dayAnchor: number, maxDailyDdPct: number): DrawdownSeverity`
  - `DD_FILL: Record<DrawdownSeverity, string>` — token strings for Recharts `fill`
  - `showsBreakerLine(range: RangeName): boolean`
  - `breakerLevel(dayAnchor: number, maxDailyDdPct: number): number | null`

Two pure functions plus their lookup tables. They are the only places where the spec's thresholds live, and they are unit-testable without rendering anything.

**Severity is computed from the window's DEEPEST drawdown**, not per point: the area gets one fill, and "how bad did it get in this window" is the question the colour should answer. A per-point gradient would need a value-keyed `linearGradient` and is not worth it.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/equityChartPolicy.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  drawdownSeverity,
  showsBreakerLine,
  breakerLevel,
  DD_FILL,
} from "./equityChartPolicy";

// A 1000-unit anchor with a 3% breaker gives a 30-unit daily loss budget, so
// the 1/3 and 2/3 boundaries land on exactly -10 and -20.
const ANCHOR = 1000;
const PCT = 3;

describe("drawdownSeverity (spec §6)", () => {
  it("is shallow below one third of the daily budget", () => {
    expect(drawdownSeverity(-9.99, ANCHOR, PCT)).toBe("shallow");
  });

  it("is moderate AT one third exactly", () => {
    expect(drawdownSeverity(-10, ANCHOR, PCT)).toBe("moderate");
  });

  it("is moderate AT two thirds exactly", () => {
    expect(drawdownSeverity(-20, ANCHOR, PCT)).toBe("moderate");
  });

  it("is severe past two thirds", () => {
    expect(drawdownSeverity(-20.01, ANCHOR, PCT)).toBe("severe");
  });

  it("treats drawdown sign-agnostically so a positive input cannot read as shallow", () => {
    // Drawdown is always <= 0 by construction, but a sign flip upstream must not
    // silently downgrade severity.
    expect(drawdownSeverity(25, ANCHOR, PCT)).toBe("severe");
  });

  it("falls back to moderate when the anchor is unset (0.0, the pre-anchor default)", () => {
    expect(drawdownSeverity(-25, 0, PCT)).toBe("moderate");
  });

  it("falls back to moderate when the breaker pct is unset", () => {
    expect(drawdownSeverity(-25, ANCHOR, 0)).toBe("moderate");
  });

  it("falls back to moderate for a null or non-finite drawdown", () => {
    expect(drawdownSeverity(null, ANCHOR, PCT)).toBe("moderate");
    expect(drawdownSeverity(Number.NaN, ANCHOR, PCT)).toBe("moderate");
  });

  it("maps every severity to a distinct fill", () => {
    const fills = Object.values(DD_FILL);
    expect(new Set(fills).size).toBe(fills.length);
  });
});

describe("showsBreakerLine (spec §7)", () => {
  it("shows on every intraday range", () => {
    for (const r of ["15m", "30m", "1h", "4h", "12h", "1d"] as const) {
      expect(showsBreakerLine(r), r).toBe(true);
    }
  });

  it("hides on every range spanning more than a day", () => {
    // The anchor is a TODAY-only value and no historical anchors are stored, so
    // drawing it across past days invites reading old equity against a threshold
    // that was never in force then.
    for (const r of ["1w", "1mo", "4mo", "6mo", "1y"] as const) {
      expect(showsBreakerLine(r), r).toBe(false);
    }
  });
});

describe("breakerLevel", () => {
  it("is the anchor less the breaker percentage", () => {
    expect(breakerLevel(1000, 3)).toBeCloseTo(970, 6);
  });

  it("is null when the anchor is unset, so no line is drawn at zero", () => {
    expect(breakerLevel(0, 3)).toBeNull();
  });

  it("is null when the percentage is unset", () => {
    expect(breakerLevel(1000, 0)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/lib/equityChartPolicy.test.ts
```

Expected: FAIL — cannot resolve `./equityChartPolicy`.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/lib/equityChartPolicy.ts`:

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/lib/equityChartPolicy.test.ts && npx tsc -b
```

Expected: PASS, clean type-check.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/equityChartPolicy.ts frontend/src/lib/equityChartPolicy.test.ts
git commit -m "feat(equity): drawdown severity ramp + breaker visibility policy"
```

---

### Task 3: Thread `expanded` and the risk block to the chart

**Files:**
- Modify: `frontend/src/components/EquitySparkline.tsx` (props only)
- Modify: `frontend/src/components/EquityPanelBody.tsx`
- Modify: `frontend/src/sections/OverviewPage.tsx:249-259` (`equityBodyProps`)
- Test: `frontend/src/components/EquitySparkline.test.tsx` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `EquitySparkline` gains `expanded?: boolean` and `risk?: { day_anchor: number; max_daily_dd_pct: number }`.
  - `EquityPanelBody` gains `risk?: RiskBlock | undefined` and forwards `expanded={fill}`.

Pure plumbing — **no visual change in this task.** Doing it separately keeps the structural pane change (Task 4) reviewable on its own.

`EquityPanelBody` already knows whether it is maximized: its `fill` prop. Do NOT infer expansion from `height` (a `"100%"` string vs the `140` default) — that couples a layout detail to a behavioural one.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/EquitySparkline.test.tsx`:

First add the two fixtures from the **Shared test fixtures** section above to the top of this file. Then append:

```tsx
describe("expanded + risk props (B1 plumbing)", () => {
  it("accepts expanded and risk without changing what it renders by default", () => {
    const { container: plain } = render(
      <EquitySparkline points={[]} series={makeSeries()} width={400} height={200} />,
    );
    const { container: withProps } = render(
      <EquitySparkline
        points={[]}
        series={makeSeries()}
        risk={{ day_anchor: 1000, max_daily_dd_pct: 3 }}
        width={400}
        height={200}
      />,
    );
    // expanded defaults to false, so passing risk alone must not alter the
    // collapsed rendering: same number of drawn series.
    expect(withProps.querySelectorAll(".recharts-area").length).toBe(
      plain.querySelectorAll(".recharts-area").length,
    );
    expect(plain.querySelectorAll(".recharts-area").length).toBeGreaterThan(0);
  });
});
```

The final assertion matters: without it, a fixture that mounts no SVG would make the comparison `0 === 0` and the test would pass while proving nothing.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx
```

Expected: FAIL — TypeScript rejects the unknown `risk` prop.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/components/EquitySparkline.tsx`, extend the props (the component's props are declared inline in its signature — add these to that object type and to the destructured parameters):

```tsx
  expanded = false,
  risk,
```

```tsx
  /** Render the maximized two-pane layout (equity + underwater). Comes from
   *  EquityPanelBody's `fill`, never inferred from `height`. */
  expanded?: boolean;
  /** Today's breaker inputs. Absent until the risk block loads. */
  risk?: { day_anchor: number; max_daily_dd_pct: number };
```

`noUnusedParameters` will flag `expanded` and `risk` while nothing reads them. To keep this task green without faking a use, reference them in the `aria-label` computation you already build — append nothing visible, but read them into a `void` statement immediately above the `return`:

```tsx
  // Consumed by Tasks 4-7; referenced here so the plumbing task type-checks.
  void expanded;
  void risk;
```

Remove those two `void` lines in Task 4 and Task 7 as the real consumers land.

In `frontend/src/components/EquityPanelBody.tsx`, add to `EquityPanelBodyProps`:

```tsx
  /** Today's risk block, for the breaker reference line. */
  risk?: RiskBlock;
```

Add `risk` to the destructured params, import the type (`import type { EquitySeries, RangeName, RiskBlock } from "@/lib/types";`), and pass both down:

```tsx
        <EquitySparkline
          points={points}
          series={series}
          height={fill ? "100%" : undefined}
          expanded={fill}
          risk={risk ? { day_anchor: risk.day_anchor, max_daily_dd_pct: risk.max_daily_dd_pct } : undefined}
        />
```

In `frontend/src/sections/OverviewPage.tsx`, add one line to `equityBodyProps`:

```tsx
    risk: snapshot?.risk,
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx src/components/EquityPanelBody.test.tsx src/sections/OverviewPage.test.tsx && npx tsc -b
```

Expected: PASS. If `EquityPanelBody.test.tsx` does not exist, drop it from the command.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx \
        frontend/src/components/EquityPanelBody.tsx frontend/src/sections/OverviewPage.tsx
git commit -m "feat(equity): thread expanded + risk block down to the chart"
```

---

### Task 4: Underwater pane in the expanded view

**Files:**
- Modify: `frontend/src/components/EquitySparkline.tsx`
- Test: `frontend/src/components/EquitySparkline.test.tsx` (append)

**Interfaces:**
- Consumes: `expanded` from Task 3.
- Produces: when `expanded`, drawdown renders in a second `ComposedChart` beneath the equity chart, marked `data-testid="underwater-pane"`. When collapsed, layout is byte-for-byte today's.

This is the structural change the legend depends on: one axis and one meaning per pane, so the legend is honest by construction instead of labelling a hidden axis.

Both charts must use `<YAxis width={52} />` so their plot areas start at the same x offset and the panes line up vertically. The underwater pane's `XAxis` is hidden (the equity pane above carries the visible one) but must keep the **same `dataKey`, `type`, `domain` and `scale`** or the two panes will not align.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/EquitySparkline.test.tsx`:

```tsx
describe("underwater pane (spec §4, §6)", () => {
  it("renders no underwater pane when collapsed", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} width={400} height={200} />,
    );
    expect(container.querySelector('[data-testid="underwater-pane"]')).toBeNull();
  });

  it("renders the underwater pane when expanded", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} expanded width={400} height={400} />,
    );
    expect(container.querySelector('[data-testid="underwater-pane"]')).not.toBeNull();
  });

  it("still mounts exactly one equity-sparkline root when expanded", () => {
    // The single-instance invariant from sub-project A: a second mounted chart
    // makes getByTestId throw across unrelated suites and doubles live chart
    // work every heartbeat. Two panes inside ONE component is the requirement.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} expanded width={400} height={400} />,
    );
    expect(container.querySelectorAll('[data-testid="equity-sparkline"]').length).toBe(1);
  });

  it("keeps drawing drawdown in the collapsed single pane", () => {
    // Collapsed must not silently lose the drawdown area when the expanded path
    // takes it over. Two areas = equity + drawdown.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} width={400} height={200} />,
    );
    expect(container.querySelectorAll(".recharts-area").length).toBeGreaterThanOrEqual(2);
  });

  it("draws drawdown exactly once when expanded — moved, not duplicated", () => {
    // Guards the failure this split invites: rendering the drawdown area in the
    // equity pane AND the underwater pane, which double-paints it and makes the
    // legend describe two things that look like one.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} expanded width={400} height={400} />,
    );
    const underwater = container.querySelector('[data-testid="underwater-pane"]')!;
    expect(underwater.querySelectorAll(".recharts-area").length).toBe(1);
    // The equity pane keeps only its own equity area.
    const total = container.querySelectorAll(".recharts-area").length;
    expect(total).toBe(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx
```

Expected: FAIL — no element with `data-testid="underwater-pane"`.

- [ ] **Step 3: Write minimal implementation**

In `EquitySparkline.tsx`, delete the `void expanded;` line from Task 3.

Extract the drawdown `<Area>` currently inside the single chart so it is rendered **either** in the main chart (collapsed) **or** in the underwater pane (expanded). Wrap the existing `<ResponsiveContainer>` and the new pane in the existing outer `div`:

```tsx
      <div className={cn("flex flex-col", expanded && "h-full")}>
        <div className={cn(expanded ? "min-h-0 flex-1" : "contents")}>
          <ResponsiveContainer width={width} height={expanded ? "100%" : height}>
            {/* ...the existing ComposedChart, unchanged, EXCEPT: render the
                drawdown <Area> and the `dd` YAxis only when !expanded... */}
          </ResponsiveContainer>
        </div>

        {expanded && (
          <div data-testid="underwater-pane" className="h-[26%] min-h-[70px]">
            <ResponsiveContainer width={width} height="100%">
              <ComposedChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="hsl(var(--border-strong))" strokeOpacity={0.45} vertical={false} />
                {/* Same dataKey/type/domain/scale as the equity pane's XAxis, and
                    the same YAxis width, or the two panes do not line up. */}
                <XAxis
                  dataKey="ts"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  scale="time"
                  hide
                />
                <YAxis
                  yAxisId="dd"
                  domain={[ddFloor, 0]}
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
                  isAnimationActive={false}
                  labelFormatter={(v: number) => formatTick(v, series.range)}
                  formatter={(v: number) => [money(v), "Drawdown"] as [string, string]}
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
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
```

Keep the collapsed path's drawdown `<Area>` and its `<YAxis yAxisId="dd" hide ... />` exactly as they are today, guarded by `{!expanded && ( ... )}`. Task 5 replaces the hard-coded `--loss` fill in **both** places.

Note `"contents"` on the collapsed wrapper: it makes the extra `div` layout-neutral so the collapsed card's box model is unchanged.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx
git commit -m "feat(equity): underwater drawdown pane in the expanded view"
```

---

### Task 5: Severity ramp and max-drawdown reference

**Files:**
- Modify: `frontend/src/components/EquitySparkline.tsx`
- Test: `frontend/src/components/EquitySparkline.test.tsx` (append)

**Interfaces:**
- Consumes: `drawdownSeverity`, `DD_FILL` (Task 2); `risk` (Task 3); both drawdown `<Area>`s (Task 4).
- Produces: no new exports.

Two things, both answering "how bad did it get in this window": the fill colour and the deepest-point
reference. Replaces the hard-coded `fill="hsl(var(--loss))"` in **both** the collapsed and expanded
drawdown areas with the ramp, keyed to the window's deepest drawdown. Per spec §6 the ramp applies in
both views — only the drawdown's *placement* differs. The max-drawdown reference is
expanded-only (spec §9).

⚠️ You cannot assert the resolved colour in jsdom. The guard below asserts on a `data-dd-severity` attribute stamped on the chart root — real rendered state a mutation breaks — and the ramp's arithmetic is already covered by Task 2's unit tests.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/EquitySparkline.test.tsx`:

```tsx
describe("drawdown severity ramp (spec §6)", () => {
  // 1000 anchor at 3% => a 30-unit daily budget. -25 is 83% consumed (severe);
  // -5 is 17% (shallow).
  const RISK = { day_anchor: 1000, max_daily_dd_pct: 3 };
  const severityOf = (container: HTMLElement) =>
    container.querySelector('[data-testid="equity-sparkline"]')?.getAttribute("data-dd-severity");

  it("stamps severe for a drawdown past two thirds of the daily budget", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} risk={RISK} width={400} height={200} />,
    );
    expect(severityOf(container)).toBe("severe");
  });

  it("stamps shallow for a small drawdown", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-5)} risk={RISK} width={400} height={200} />,
    );
    expect(severityOf(container)).toBe("shallow");
  });

  it("falls back to moderate when no risk block has loaded", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} width={400} height={200} />,
    );
    expect(severityOf(container)).toBe("moderate");
  });

  it("stamps the same severity in the expanded view", () => {
    // The ramp applies in BOTH views (spec §6) — placement differs, colour does not.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} risk={RISK} expanded width={400} height={400} />,
    );
    expect(severityOf(container)).toBe("severe");
  });
});

describe("max-drawdown reference (spec §6)", () => {
  it("marks the deepest point in the expanded underwater pane", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} expanded width={400} height={400} />,
    );
    expect(container.querySelector('[data-testid="max-dd-reference"]')).not.toBeNull();
  });

  it("omits it in the collapsed card", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} width={400} height={200} />,
    );
    expect(container.querySelector('[data-testid="max-dd-reference"]')).toBeNull();
  });

  it("omits it when the window never went underwater", () => {
    // makeSeries has peak === equity throughout, so minDrawdown is 0 and a
    // "deepest point" reference would be a line at zero claiming a drawdown
    // that never happened.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeries()} expanded width={400} height={400} />,
    );
    expect(container.querySelector('[data-testid="max-dd-reference"]')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx
```

Expected: FAIL — `data-dd-severity` is `null`.

- [ ] **Step 3: Write minimal implementation**

In `EquitySparkline.tsx`, add the import:

```tsx
import { drawdownSeverity, DD_FILL } from "@/lib/equityChartPolicy";
```

Below the existing `minDrawdown` computation (which already gives the window's deepest drawdown):

```tsx
  // One fill for the whole area, keyed to the DEEPEST drawdown in the window —
  // "how bad did it get here". A per-point gradient would need a value-keyed
  // linearGradient and buys nothing at these sizes.
  const ddSeverity = drawdownSeverity(
    minDrawdown,
    risk?.day_anchor ?? 0,
    risk?.max_daily_dd_pct ?? 0,
  );
  const ddFill = DD_FILL[ddSeverity];
```

Stamp it on the chart root (the `div` carrying `data-testid="equity-sparkline"`):

```tsx
      data-dd-severity={ddSeverity}
```

Replace `fill="hsl(var(--loss))"` with `fill={ddFill}` in **both** drawdown `<Area>`s (collapsed and underwater). Raise the underwater pane's `fillOpacity` from `0.18` to `0.55` — in its own pane it is the subject, not a background wash; leave the collapsed one at `0.18`.

Delete the `void risk;` line from Task 3 if it is still present.

Then add the **max-drawdown reference** (spec §6) inside the underwater pane's `ComposedChart`, after its `<YAxis>`:

```tsx
                {minDrawdown < 0 && (
                  <ReferenceLine
                    yAxisId="dd"
                    y={minDrawdown}
                    stroke={ddFill}
                    strokeDasharray="3 3"
                    strokeOpacity={0.9}
                    label={{
                      value: `max ${money(minDrawdown)}`,
                      position: "insideTopRight",
                      fill: "hsl(var(--text-muted))",
                      fontSize: 10,
                    }}
                  />
                )}
```

and, inside the underwater pane's wrapper `div`, the testable marker:

```tsx
            {minDrawdown < 0 && (
              <span data-testid="max-dd-reference" className="sr-only">
                Deepest drawdown in this window: {money(minDrawdown)}
              </span>
            )}
```

The `minDrawdown < 0` guard is load-bearing: when the window never went underwater, `minDrawdown` is
`0` and an unguarded reference would draw a line along the zero axis labelled as a maximum drawdown
that never occurred.

Add `ReferenceLine` to the `recharts` import if it is not already there.

The `sr-only` span rather than a `data-testid` on `<ReferenceLine>`: Recharts filters unknown props
on some elements, so an attribute placed on the chart primitive may never reach the DOM. A sibling
element is real rendered state, is announced to assistive tech, and fails when the reference is
wrongly present or wrongly absent.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx src/lib/equityChartPolicy.test.ts && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx
git commit -m "feat(equity): colour drawdown by severity instead of a flat red"
```

---

### Task 6: High-water-mark line

**Files:**
- Modify: `frontend/src/components/EquitySparkline.tsx`
- Test: `frontend/src/components/EquitySparkline.test.tsx` (append)

**Interfaces:**
- Consumes: `ChartRow.peak` (Task 1).
- Produces: no new exports.

A thin line on the equity pane's left axis — same unit and scale as equity and balance, so no axis-honesty problem. Visually subordinate: it is a reference, and the gap between it and the equity area *is* the drawdown the underwater pane quantifies.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/EquitySparkline.test.tsx`:

```tsx
describe("high-water mark line (spec §5)", () => {
  it("draws two lines — balance and the high-water mark", () => {
    // Before this task there is exactly one <Line> (balance). The peak line is
    // the second, so a count of 2 fails if it was never added AND if it was
    // added as an Area by mistake.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} width={400} height={200} />,
    );
    expect(container.querySelectorAll(".recharts-line").length).toBe(2);
  });

  it("includes the peak in the y-axis fit so the line cannot sit off-canvas", () => {
    // A peak far above every equity value must widen the domain. If the fit
    // ignores peak, the line renders outside the plot area and is invisible
    // while the DOM still claims it exists. Fixture peak is 1000 and the
    // deepest equity is 500, so the axis must reach past 1000.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-500)} width={400} height={200} />,
    );
    const ticks = [...container.querySelectorAll(".recharts-cartesian-axis-tick-value")]
      .map((n) => Number((n.textContent || "").replace(/,/g, "")))
      .filter((n) => Number.isFinite(n));
    expect(ticks.length).toBeGreaterThan(0);
    expect(Math.max(...ticks)).toBeGreaterThanOrEqual(1000);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx
```

Expected: FAIL — no line named `peak`.

- [ ] **Step 3: Write minimal implementation**

Include peak in the y-fit. Replace the `allValues` line:

```tsx
  const peakValues = rows.map((r) => r.peak).filter(isFinite_);
  const allValues = [...equityValues, ...balanceValues, ...peakValues];
```

Add the line to the equity pane, **before** the equity `<Area>` so equity paints over it:

```tsx
          <Line
            yAxisId="equity"
            type="stepAfter"
            dataKey="peak"
            name="peak"
            stroke="hsl(var(--text-muted))"
            strokeWidth={1}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
            activeDot={false}
            connectNulls
          />
```

`stepAfter` because a high-water mark is a ratchet — it holds flat then jumps; `monotone` would draw a smooth ramp between peaks that never happened. `connectNulls` bridges buckets where the backend omitted `peak` rather than breaking the reference into fragments.

Extend the tooltip formatter's name mapping to include `peak`:

```tsx
              name === "equity" ? "Equity"
                : name === "balance" ? "Balance"
                : name === "peak" ? "High-water mark"
                : "Drawdown",
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx
git commit -m "feat(equity): draw the high-water mark"
```

---

### Task 7: Daily breaker reference line

**Files:**
- Modify: `frontend/src/components/EquitySparkline.tsx`
- Test: `frontend/src/components/EquitySparkline.test.tsx` (append)

**Interfaces:**
- Consumes: `showsBreakerLine`, `breakerLevel` (Task 2); `risk` (Task 3).
- Produces: no new exports.

Drawn on intraday ranges only. On `1w` and longer it is absent entirely — not greyed, not labelled-as-stale — because `day_anchor` describes today and no historical anchors exist.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/EquitySparkline.test.tsx`:

```tsx
describe("daily breaker line (spec §7)", () => {
  const risk = { day_anchor: 1000, max_daily_dd_pct: 3 };

  it("draws the breaker on an intraday range", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeries("1d")} risk={risk} width={400} height={200} />,
    );
    expect(container.querySelector('[data-testid="breaker-line"]')).not.toBeNull();
  });

  it("omits the breaker on a multi-day range", () => {
    // day_anchor is TODAY-only and no historical anchors are stored, so a line
    // spanning past days would be read against a threshold never in force then.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeries("1w")} risk={risk} width={400} height={200} />,
    );
    expect(container.querySelector('[data-testid="breaker-line"]')).toBeNull();
  });

  it("omits the breaker when the anchor has not been set yet", () => {
    const { container } = render(
      <EquitySparkline
        points={[]}
        series={makeSeries("1d")}
        risk={{ day_anchor: 0, max_daily_dd_pct: 3 }}
        width={400}
        height={200}
      />,
    );
    expect(container.querySelector('[data-testid="breaker-line"]')).toBeNull();
  });

  it("omits the breaker when no risk block has loaded", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeries("1d")} width={400} height={200} />,
    );
    expect(container.querySelector('[data-testid="breaker-line"]')).toBeNull();
  });
});
```

`makeSeries` must take an optional range name (default `"1d"`) and set it on the returned series.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx
```

Expected: FAIL — no `breaker-line` element.

- [ ] **Step 3: Write minimal implementation**

Add the import:

```tsx
import { showsBreakerLine, breakerLevel } from "@/lib/equityChartPolicy";
```

Compute it once, near `ddSeverity`:

```tsx
  const breakerY = showsBreakerLine(series.range)
    ? breakerLevel(risk?.day_anchor ?? 0, risk?.max_daily_dd_pct ?? 0)
    : null;
```

Add to the equity pane, after the `<YAxis>` declarations and before the series so it paints beneath them:

```tsx
          {breakerY !== null && (
            <ReferenceLine
              yAxisId="equity"
              y={breakerY}
              stroke="hsl(var(--loss))"
              strokeDasharray="6 4"
              strokeOpacity={0.8}
              ifOverflow="extendDomain"
              label={{
                value: "daily breaker",
                position: "insideBottomLeft",
                fill: "hsl(var(--loss))",
                fontSize: 10,
              }}
              // Recharts does not forward arbitrary props to the rendered line,
              // so the testable marker goes on a wrapper the chart does render.
              {...{ "data-testid": "breaker-line" }}
            />
          )}
```

Add `ReferenceLine` to the existing `recharts` import.

⚠️ If `data-testid` does not survive onto a DOM node (Recharts filters unknown props on some elements), do **not** delete the assertion — instead render the marker as a sibling of the chart:
`{breakerY !== null && <span data-testid="breaker-line" className="sr-only">Daily breaker at {money(breakerY)}</span>}`
placed inside the chart root `div`. That is real rendered state, it is accessible, and it fails when the line is wrongly drawn or wrongly omitted.

`ifOverflow="extendDomain"` matters: when the breaker sits below every plotted equity value the default clips it silently, and the operator sees no line precisely when they are closest to being stopped out.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx
git commit -m "feat(equity): daily breaker reference on intraday ranges"
```

---

### Task 8: Legend

**Files:**
- Create: `frontend/src/components/EquityLegend.tsx`
- Modify: `frontend/src/components/EquitySparkline.tsx`
- Test: `frontend/src/components/EquityLegend.test.tsx`
- Test: `frontend/src/components/EquitySparkline.test.tsx` (append)

**Interfaces:**
- Consumes: `breakerY` (Task 7), `expanded` (Task 3), `DD_FILL`/`ddSeverity` (Tasks 2, 5).
- Produces: `EquityLegend({ entries }: { entries: LegendEntry[] })` where
  `interface LegendEntry { key: string; label: string; swatch: string; dashed?: boolean }`.

One legend per pane. Entries carry the same token strings the series are drawn with, so a retune moves both together. **Not interactive** — no click-to-toggle; a hidden series is new state every screenshot and bug report has to account for, and nobody asked for it.

The breaker entry appears and disappears with the line, so nothing points at an invisible reference.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/EquityLegend.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquityLegend } from "./EquityLegend";

describe("EquityLegend", () => {
  it("renders one labelled entry per series", () => {
    render(
      <EquityLegend
        entries={[
          { key: "equity", label: "Equity", swatch: "hsl(var(--accent))" },
          { key: "balance", label: "Balance", swatch: "hsl(var(--text-muted))" },
        ]}
      />,
    );
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("Balance")).toBeInTheDocument();
    expect(screen.getAllByTestId("legend-swatch").length).toBe(2);
  });

  it("renders nothing at all for an empty entry list", () => {
    const { container } = render(<EquityLegend entries={[]} />);
    expect(container.querySelector('[data-testid="equity-legend"]')).toBeNull();
  });

  it("is not interactive — no buttons to toggle series", () => {
    render(<EquityLegend entries={[{ key: "equity", label: "Equity", swatch: "x" }]} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
```

Append to `frontend/src/components/EquitySparkline.test.tsx`:

```tsx
describe("legend wiring (spec §8)", () => {
  const RISK = { day_anchor: 1000, max_daily_dd_pct: 3 };

  it("names every drawn series in the expanded view", () => {
    render(
      <EquitySparkline
        points={[]}
        series={makeSeriesWithDrawdown(-25, "1d")}
        expanded
        risk={RISK}
        width={400}
        height={400}
      />,
    );
    for (const label of ["Equity", "Balance", "High-water mark", "Drawdown", "Daily breaker"]) {
      expect(screen.getByText(label), label).toBeInTheDocument();
    }
  });

  it("drops the breaker entry on ranges where the line is not drawn", () => {
    render(
      <EquitySparkline
        points={[]}
        series={makeSeriesWithDrawdown(-25, "1w")}
        expanded
        risk={RISK}
        width={400}
        height={400}
      />,
    );
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.queryByText("Daily breaker")).toBeNull();
  });

  it("renders no legend in the collapsed card", () => {
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} width={400} height={200} />,
    );
    expect(container.querySelector('[data-testid="equity-legend"]')).toBeNull();
  });
});
```

`makeSeriesWithDrawdown` needs an optional second argument for the range name.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/EquityLegend.test.tsx src/components/EquitySparkline.test.tsx
```

Expected: FAIL — cannot resolve `./EquityLegend`.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/EquityLegend.tsx`:

```tsx
export interface LegendEntry {
  key: string;
  label: string;
  /** The same colour string the series is drawn with, so a token retune moves
   *  the swatch and the series together. */
  swatch: string;
  dashed?: boolean;
}

/**
 * Static key for one chart pane. Deliberately NOT interactive: a click-to-hide
 * series is hidden state that every screenshot and bug report then has to
 * account for, and nothing asked for it.
 */
export function EquityLegend({ entries }: { entries: LegendEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div
      data-testid="equity-legend"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 pt-1 text-[11px] text-muted-foreground"
    >
      {entries.map((e) => (
        <span key={e.key} className="inline-flex items-center gap-1.5">
          <span
            data-testid="legend-swatch"
            aria-hidden
            className="inline-block h-0.5 w-3 rounded-full"
            style={
              e.dashed
                ? { backgroundImage: `repeating-linear-gradient(90deg, ${e.swatch} 0 4px, transparent 4px 7px)` }
                : { backgroundColor: e.swatch }
            }
          />
          {e.label}
        </span>
      ))}
    </div>
  );
}
```

In `EquitySparkline.tsx`, import it and build the two entry lists. Render the equity legend directly beneath the equity pane's container and the drawdown legend beneath the underwater pane, **only when `expanded`**:

```tsx
  const equityLegend: LegendEntry[] = [
    { key: "equity", label: "Equity", swatch: "hsl(var(--accent))" },
    { key: "balance", label: "Balance", swatch: "hsl(var(--text-muted))" },
    { key: "peak", label: "High-water mark", swatch: "hsl(var(--text-muted))", dashed: true },
    ...(breakerY !== null
      ? [{ key: "breaker", label: "Daily breaker", swatch: "hsl(var(--loss))", dashed: true }]
      : []),
  ];
  const underwaterLegend: LegendEntry[] = [
    { key: "drawdown", label: "Drawdown", swatch: ddFill },
  ];
```

Import the type alongside the component:
`import { EquityLegend, type LegendEntry } from "@/components/EquityLegend";`

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/EquityLegend.test.tsx src/components/EquitySparkline.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Full suite, build, and commit**

```bash
cd frontend && npm test && npm run build
```

`npm test` takes 4-7 minutes — run it in the FOREGROUND and wait. Known load-sensitive flakes that pass in isolation: `src/App.test.tsx > "gates on token"`, `src/App.test.tsx > "navigates to the real Positions page"`, plus `Controls` and `StrategiesTab`. Re-run any of those in isolation and report BOTH results. Any OTHER failure is real.

⚠️ Read pass/fail from the summary line, never from an exit code behind a pipe — `npm test | tail` reports *tail's* status.

```bash
git add frontend/src/components/EquityLegend.tsx frontend/src/components/EquityLegend.test.tsx \
        frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx
git commit -m "feat(equity): name every series with a per-pane legend"
```

---

## Manual verification (not unit-testable)

jsdom resolves no colour and computes no layout, so the pane split, the ramp and the alignment need a real browser. Use the recipe proven in A and A2 — it never touches the live bot:

1. `npm run build` in the worktree's `frontend/`.
2. From the worktree root: `TITAN_GUI_PORT=8899 TITAN_GUI_TOKEN=layoutcheck <main-checkout>/.venv/bin/python -m src.ops.web.devserver` (give it ~10s to bind; confirm with `ss -tlnp` before and after that 8770 and 32768-9 stayed the bot's).
3. Open `http://127.0.0.1:8899`, enter `layoutcheck`, maximize the Equity panel.
4. Confirm:
   - the two panes share an x-axis and their plot areas line up on the left,
   - the high-water line reads as a subordinate ratchet above the equity area, not a competing series,
   - the drawdown pane is legible at depth rather than a faint wash,
   - the legend names every drawn series and nothing it names is invisible,
   - switching to `1w` removes BOTH the breaker line and its legend entry,
   - the collapsed 140px card looks unchanged from before this branch.
5. Screenshot for the record, then stop the devserver and re-check `ss -tlnp`.

⚠️ The devserver's fake controller reports equity 10,000 flat with no drawdown, so the ramp will sit at its fallback. To see real severities, either drive it with a series whose `peak` exceeds `equity`, or read the real numbers instead: the live account is ~457 against a peak of 469.29 (about −2.6%). A browser pass against fake data proves layout and wiring, not that the ramp picks sensible severities — that is Task 2's unit tests.

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquitySparkline } from "./EquitySparkline";
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

describe("EquitySparkline", () => {
  it("renders a 'No data yet' empty state when points is empty", () => {
    render(<EquitySparkline points={[]} />);
    expect(screen.getByText(/no data yet/i)).toBeInTheDocument();
  });

  it("renders the chart container without throwing when given points", () => {
    const points = [
      { t: 1, equity: 10000 },
      { t: 2, equity: 10050 },
      { t: 3, equity: 9980 },
    ];
    render(<EquitySparkline points={points} />);
    expect(screen.getByTestId("equity-sparkline")).toBeInTheDocument();
    expect(screen.queryByText(/no data yet/i)).not.toBeInTheDocument();
  });

  it("breaks the equity line into separate path segments at a gap, not a bridge", () => {
    // jsdom does no layout, so Recharts' <ResponsiveContainer> needs explicit
    // pixel dimensions here (rather than the "100%" default) to mount real
    // SVG content instead of measuring 0x0 and rendering nothing.
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
    const { container } = render(
      <EquitySparkline points={[]} series={series as never} width={400} height={200} />,
    );
    expect(screen.getByTestId("equity-sparkline")).toBeInTheDocument();

    // The equity line's own outline path (not the fill, which always closes
    // back to the baseline). With one real point on each side of the null and
    // connectNulls left at its default false, a broken line renders as two
    // independent single-point subpaths ("M..Z" "M..Z"): two "M" commands and
    // no "L" connecting them. A regression that bridged the gap (connectNulls
    // true, or the null row silently dropped) would instead render ONE
    // continuous subpath joining both points with an "L" — this assertion
    // fails in that case, unlike a bare "some svg exists" check.
    const equityCurve = container.querySelector("path.recharts-area-curve");
    expect(equityCurve).not.toBeNull();
    const d = equityCurve!.getAttribute("d")!;
    expect(d.match(/M/g)).toHaveLength(2);
    expect(d).not.toContain("L");
  });

  it("gives drawdown its own y-axis so a realistic drawdown is visible, not a sliver on the equity axis", () => {
    // Every prior fixture had peak === equity (drawdown always 0), which is
    // exactly what let a shared-axis bug through: a real drawdown (tens of
    // units against an equity in the thousands) collapses to a ~1-2px sliver
    // pinned to the plot's bottom edge when it shares the equity/balance axis.
    const series = {
      range: "1d", tier: "coarse" as const, bucket_s: 300,
      series: ["equity", "balance", "peak"],
      points: [
        { ts: 1000, equity: 10000, balance: 9990, peak: 10000 },
        { ts: 1500, equity: 9980, balance: 9990, peak: 10000 },
        { ts: 2000, equity: 9920, balance: 9990, peak: 10080 },
        { ts: 2500, equity: 9960, balance: 9990, peak: 10080 },
        { ts: 3000, equity: 10080, balance: 10000, peak: 10080 },
      ],
      coverage: { first_sample_ts: 1000, n: 5, series_first_ts: {}, gaps: [] as [number, number][] },
    };
    const { container } = render(
      <EquitySparkline points={[]} series={series as never} width={400} height={200} />,
    );

    // Drawdown is the first Area in source order (rendered first/behind);
    // equity is the second. Both produce a ".recharts-area-area" fill path.
    const areaFills = container.querySelectorAll("path.recharts-area-area");
    expect(areaFills).toHaveLength(2);
    const drawdownPath = areaFills[0].getAttribute("d")!;
    const ys = Array.from(drawdownPath.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)).map((m) => Number(m[2]));
    const span = Math.max(...ys) - Math.min(...ys);
    // Prior to giving drawdown its own axis, this span measured ~1.5px out of
    // a ~148px plot area for realistic magnitudes. On its own axis it should
    // occupy a large, clearly visible fraction of the plot.
    expect(span).toBeGreaterThan(60);

    // The balance line must actually render (this only holds if the chart
    // uses ComposedChart — Recharts' AreaChart silently drops <Line>
    // children with no error, which is a separate, adjacent bug this fix
    // also corrects).
    expect(container.querySelector("path.recharts-line-curve")).not.toBeNull();
  });

  /**
   * Assert on the RENDERED DOM, never on component source.
   *
   * The previous version of this guard did
   * `expect(EquitySparkline.toString()).not.toContain("isAnimationActive={true}")`,
   * which could not fail for two independent reasons: JSX compiles away, so
   * that literal string never exists in the output, and `.toString()` covers
   * only the outer function while three of the four series live in the separate
   * top-level `SeriesChart`.
   *
   * These are the real signatures recharts 2.15 leaves behind when a series
   * animates (verified by mutation — flipping any one series to
   * `isAnimationActive={true}` makes this fail):
   *   - an animated <Area> emits `<clipPath id="animationClipPath-…">` and
   *     wraps its curve in `clip-path="url(#animationClipPath-…)"`,
   *   - an animated <Line> gets a `stroke-dasharray` on its curve path.
   */
  function expectNoAnimation(container: HTMLElement) {
    expect(container.querySelectorAll('[id^="animationClipPath"]')).toHaveLength(0);
    expect(container.querySelectorAll('[clip-path^="url(#animationClipPath"]')).toHaveLength(0);
    expect(container.querySelectorAll("animate, animateTransform, animateMotion")).toHaveLength(0);
    // <Area> animates via clip-path (checked above). <Line> animates via stroke-dasharray.
    // Exclude the high-water mark curve (data-testid="hwm-line") which has intentional dashed styling.
    const curves = container.querySelectorAll("path.recharts-curve:not([data-testid='hwm-line'])");
    expect(curves.length).toBeGreaterThan(0);   // or the assertion is vacuous
    curves.forEach((c) => expect(c.hasAttribute("stroke-dasharray")).toBe(false));
  }

  it("never animates on the legacy buffer path", () => {
    const { container } = render(
      <EquitySparkline
        points={[{ t: 1, equity: 10000 }, { t: 2, equity: 10050 }, { t: 3, equity: 9980 }]}
        width={400}
        height={200}
      />,
    );
    expectNoAnimation(container);
  });

  it("never animates any of the series-path series", () => {
    // Covers all three (drawdown Area, balance Line, equity Area) — the ones the
    // old source-string check could not see at all.
    const series = {
      range: "1d", tier: "coarse" as const, bucket_s: 300,
      series: ["equity", "balance", "peak"],
      points: [
        { ts: 1000, equity: 10000, balance: 9990, peak: 10000 },
        { ts: 1500, equity: 9950, balance: 9990, peak: 10000 },
        { ts: 2000, equity: 10080, balance: 10000, peak: 10080 },
      ],
      coverage: { first_sample_ts: 1000, n: 3, series_first_ts: {}, gaps: [] as [number, number][] },
    };
    const { container } = render(
      <EquitySparkline points={[]} series={series as never} width={400} height={200} />,
    );
    // all four graphical series really are on screen, so this isn't vacuous:
    // drawdown area + balance line + peak line + equity area
    expect(container.querySelectorAll("path.recharts-area-area")).toHaveLength(2);
    expect(container.querySelectorAll("path.recharts-line-curve")).toHaveLength(2);
    expectNoAnimation(container);
  });

  // ---- I4: an absent series key must not blank the chart ----

  it("renders when the registry drops `balance` from the series entirely", () => {
    // Phase 1 builds a point as one tuple entry per registered series, so
    // removal is exactly as easy as addition. `undefined` sails through a
    // `!== null` filter, and one `undefined` in the domain array makes
    // `Math.min(...)` NaN — a blank chart with no error and no empty state.
    const series = {
      range: "1d", tier: "coarse" as const, bucket_s: 300,
      series: ["equity"],
      points: [
        { ts: 1000, equity: 10000 },
        { ts: 1500, equity: 10050 },
        { ts: 2000, equity: 9980 },
      ],
      coverage: { first_sample_ts: 1000, n: 3, series_first_ts: {}, gaps: [] as [number, number][] },
    };
    const { container } = render(
      <EquitySparkline points={[]} series={series as never} width={400} height={200} />,
    );

    expect(screen.queryByText(/no data/i)).not.toBeInTheDocument();
    const equityCurve = container.querySelector("path.recharts-area-curve");
    expect(equityCurve).not.toBeNull();
    const d = equityCurve!.getAttribute("d")!;
    expect(d).not.toMatch(/NaN/);
    // a real, drawn curve — three plotted vertices, not a degenerate/empty path
    const coords = Array.from(d.matchAll(/(-?[\d.]+),(-?[\d.]+)/g));
    expect(coords.length).toBeGreaterThanOrEqual(3);
    coords.forEach(([, x, y]) => {
      expect(Number.isFinite(Number(x))).toBe(true);
      expect(Number.isFinite(Number(y))).toBe(true);
    });
    // and the readout is a real number, not "NaN"
    expect(screen.getByTestId("equity-sparkline").textContent).not.toMatch(/NaN/);
  });

  it("labels the delta's basis differently on the two paths", () => {
    const { unmount } = render(
      <EquitySparkline points={[{ t: 1, equity: 10000 }, { t: 2, equity: 10050 }]} width={400} height={200} />,
    );
    expect(screen.getByTestId("equity-delta-basis")).toHaveTextContent("session");
    unmount();

    const series = {
      range: "4h", tier: "fine" as const, bucket_s: 30,
      series: ["equity", "balance", "peak"],
      points: [{ ts: 1000, equity: 10000, balance: 9990, peak: 10000 }],
      coverage: { first_sample_ts: 1000, n: 1, series_first_ts: {}, gaps: [] as [number, number][] },
    };
    render(<EquitySparkline points={[]} series={series as never} width={400} height={200} />);
    expect(screen.getByTestId("equity-delta-basis")).toHaveTextContent("4h");
  });
});

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

  it("never lets a pane's numeric height go negative, even at a pathologically small total", () => {
    // Mutation this pins: if the `underwaterHeight` clamp in EquitySparkline.tsx
    // were relaxed from `Math.min(numericTotal, Math.max(UNDERWATER_MIN_PX, ...))`
    // back to a bare `Math.max(UNDERWATER_MIN_PX, ...)` (no upper clamp to the
    // total), then at height=50 underwaterHeight would compute to 70 (the
    // floor), and mainHeight = 50 - 70 = -20 — a negative height handed
    // straight to Recharts, which does not hard-fail on it (only warns), so it
    // would ship as a silently blank equity pane rather than a visible crash.
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} expanded width={400} height={50} />,
    );
    const panes = container.querySelectorAll(".recharts-responsive-container");
    // Both panes still mount structurally (degrade predictably), not vacuous.
    expect(panes.length).toBe(2);
    panes.forEach((pane) => {
      const h = parseFloat((pane as HTMLElement).style.height);
      expect(Number.isFinite(h)).toBe(true);
      expect(h).toBeGreaterThanOrEqual(0);
    });
  });

  it("lines up the two panes' plot areas at the same x offset", () => {
    // The whole point of the split: <YAxis width={52} /> parity on both panes
    // plus a matching XAxis (dataKey/type/domain/scale) makes the equity and
    // underwater plot areas start at the same left edge. Assert on RENDERED
    // geometry (the grid line's x1), not on the YAxis width prop itself — a
    // prop-level assertion would not catch two panes whose axes drift apart
    // in a way that still individually "looks right".
    const { container } = render(
      <EquitySparkline points={[]} series={makeSeriesWithDrawdown(-25)} expanded width={400} height={400} />,
    );
    const surfaces = container.querySelectorAll("svg.recharts-surface");
    expect(surfaces.length).toBe(2); // one per pane — equity, then underwater
    const [equityX1, underwaterX1] = Array.from(surfaces).map((surface) => {
      const gridLine = surface.querySelector(".recharts-cartesian-grid-horizontal line");
      expect(gridLine).not.toBeNull();
      return gridLine!.getAttribute("x1");
    });
    expect(equityX1).not.toBeNull();
    expect(underwaterX1).toBe(equityX1);
  });
});

describe("EquitySparkline sizing", () => {
  const points = [
    { t: 0, equity: 10000 },
    { t: 1, equity: 10050 },
  ];

  it("defaults to the compact 140px strip", () => {
    render(<EquitySparkline points={points} />);
    expect(screen.getByTestId("equity-sparkline")).toHaveStyle({ height: "140px" });
  });

  it("accepts a percentage height so it can fill a maximized panel", () => {
    render(<EquitySparkline points={points} height="100%" />);
    expect(screen.getByTestId("equity-sparkline")).toHaveStyle({ height: "100%" });
  });
});

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

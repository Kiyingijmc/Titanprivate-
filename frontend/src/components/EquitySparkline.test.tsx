import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EquitySparkline } from "./EquitySparkline";

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
    const curves = container.querySelectorAll("path.recharts-curve");
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
    // all three graphical series really are on screen, so this isn't vacuous
    expect(container.querySelectorAll("path.recharts-area-area")).toHaveLength(2);
    expect(container.querySelectorAll("path.recharts-line-curve")).toHaveLength(1);
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

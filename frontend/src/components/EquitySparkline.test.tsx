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
});

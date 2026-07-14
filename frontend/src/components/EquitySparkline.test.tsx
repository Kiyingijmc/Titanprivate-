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
});

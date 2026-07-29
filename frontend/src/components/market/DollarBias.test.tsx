import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DollarBias } from "./DollarBias";
import type { DollarBias as DollarBiasData } from "@/lib/types";

const computed: DollarBiasData = {
  source: "computed",
  value: null,
  bias: 37.5,
  trend: [10, 18, 25, 30, 37.5],
  contributors: [
    { symbol: "USDJPY", contribution: 24.0 },
    { symbol: "EURUSD", contribution: -8.0 },
  ],
};

describe("DollarBias", () => {
  it("renders the bias value and a 'computed' source badge", () => {
    render(<DollarBias data={computed} />);
    expect(screen.getByTestId("dollar-bias")).toBeInTheDocument();
    expect(screen.getByText(/37\.5/)).toBeInTheDocument();
    expect(screen.getByText(/computed/i)).toBeInTheDocument();
  });

  it("renders contributor symbols", () => {
    render(<DollarBias data={computed} />);
    expect(screen.getByText("USDJPY")).toBeInTheDocument();
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
  });

  it("renders a degraded/empty state when source is 'unavailable'", () => {
    render(
      <DollarBias
        data={{ source: "unavailable", value: null, bias: 0, trend: [], contributors: [] }}
      />
    );
    expect(screen.getByText(/dollar bias unavailable/i)).toBeInTheDocument();
  });

  it("renders the degraded/empty state when data is undefined", () => {
    render(<DollarBias data={undefined} />);
    expect(screen.getByText(/dollar bias unavailable/i)).toBeInTheDocument();
  });

  it("renders a LIVE index badge when source is 'index'", () => {
    render(
      <DollarBias
        data={{ source: "index", value: 104.32, bias: 42, trend: [103.9, 104.32], contributors: [] }}
      />
    );
    expect(screen.getByText(/live/i)).toBeInTheDocument();
  });
});

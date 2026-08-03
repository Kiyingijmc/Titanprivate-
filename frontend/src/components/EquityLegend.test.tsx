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

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatTiles } from "./StatTiles";

const arb = { stats: { submitted: 4, approved: 3, blocked_by: { opposition: 1 } }, throttle: { enabled: false, current_mult: 1 } };

describe("StatTiles", () => {
  it("renders equity and a signed day-pnl tile with tone", () => {
    render(<StatTiles account={{ balance: 10000, equity: 9500 }} arbiter={arb} dayPnl={-500} openCount={2} />);
    expect(screen.getByText("9,500.00")).toBeInTheDocument();
    expect(screen.getByTestId("tile-daypnl").getAttribute("data-tone")).toBe("loss");
  });

  it("renders profit tone for a positive day-pnl", () => {
    render(<StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={500} openCount={1} />);
    expect(screen.getByTestId("tile-daypnl").getAttribute("data-tone")).toBe("profit");
  });

  it("renders open position count and arbiter approved/blocked", () => {
    render(<StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={0} openCount={2} />);
    expect(screen.getByTestId("tile-open-positions").textContent).toContain("2");
    expect(screen.getByTestId("tile-arbiter").textContent).toContain("3");
    expect(screen.getByTestId("tile-arbiter").textContent).toContain("1");
  });
});

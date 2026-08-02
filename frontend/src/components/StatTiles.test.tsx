import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatTiles } from "./StatTiles";

const arb = { stats: { submitted: 4, approved: 3, blocked_by: { opposition: 1 } }, throttle: { enabled: false, current_mult: 1 } };

describe("StatTiles", () => {
  it("renders equity and a signed day-pnl tile with tone", () => {
    render(<StatTiles account={{ balance: 10000, equity: 9500 }} arbiter={arb} dayPnl={-500} openPnl={0} openCount={2} />);
    expect(screen.getByText("9,500.00")).toBeInTheDocument();
    expect(screen.getByTestId("tile-daypnl").getAttribute("data-tone")).toBe("loss");
  });

  it("renders profit tone for a positive day-pnl", () => {
    render(<StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={500} openPnl={0} openCount={1} />);
    expect(screen.getByTestId("tile-daypnl").getAttribute("data-tone")).toBe("profit");
  });

  it("renders a live Open P&L tile summed across orders, with signed tone", () => {
    render(<StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={0} openPnl={12.5} openCount={2} />);
    const tile = screen.getByTestId("tile-openpnl");
    expect(tile.getAttribute("data-tone")).toBe("profit");
    expect(tile.textContent).toContain("+12.50");
  });

  it("renders loss tone for a negative Open P&L", () => {
    render(<StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={0} openPnl={-6} openCount={1} />);
    expect(screen.getByTestId("tile-openpnl").getAttribute("data-tone")).toBe("loss");
  });

  it("renders open position count and arbiter approved/blocked", () => {
    render(<StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={0} openPnl={0} openCount={2} />);
    expect(screen.getByTestId("tile-open-positions").textContent).toContain("2");
    expect(screen.getByTestId("tile-arbiter").textContent).toContain("3");
    expect(screen.getByTestId("tile-arbiter").textContent).toContain("1");
  });

  // 2026-08-02: the dashboard read "Open Positions 0" while two limits rested
  // at the broker. Resting orders are committed risk and must be on the KPI row.
  it("shows resting order count alongside open positions", () => {
    render(
      <StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={0}
        openPnl={0} openCount={0} pendingCount={2} />
    );
    expect(screen.getByTestId("tile-open-positions").textContent).toContain("0 / 2");
  });

  // The tile used to be fed `equity - balance`, which is 0.00 whenever nothing
  // is open — a confident-looking number that was never day P&L at all.
  it("renders an em dash, not 0.00, when the day is not yet anchored", () => {
    render(
      <StatTiles account={{ balance: 10000, equity: 10500 }} arbiter={arb} dayPnl={null}
        openPnl={0} openCount={0} />
    );
    const tile = screen.getByTestId("tile-daypnl");
    expect(tile.textContent).toContain("—");
    expect(tile.textContent).not.toContain("0.00");
    expect(tile.getAttribute("data-tone")).toBe("unanchored");
  });
});

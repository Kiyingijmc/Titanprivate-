import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskPanel } from "./RiskPanel";
import type { RiskBlock } from "@/lib/types";

const healthy: RiskBlock = {
  day_anchor: 458.9, day_pnl: -1.65, day_pnl_pct: -0.36,
  max_daily_dd_pct: 3, can_trade: true,
  book_risk: 12.4, book_risk_pct: 2.71, max_book_risk_pct: 5, blocker: null,
};

describe("RiskPanel", () => {
  it("shows the day anchor, not the boot balance, behind day P&L", () => {
    render(<RiskPanel risk={healthy} />);
    expect(screen.getByText(/458\.90/)).toBeInTheDocument();
    expect(screen.getByText(/-1\.65/)).toBeInTheDocument();
  });

  it("reports an armed breaker and a computable book", () => {
    render(<RiskPanel risk={healthy} />);
    expect(screen.getByTestId("risk-breaker-state").getAttribute("data-state")).toBe("ok");
  });

  it("surfaces a tripped daily drawdown breaker", () => {
    render(<RiskPanel risk={{ ...healthy, can_trade: false }} />);
    const el = screen.getByTestId("risk-breaker-state");
    expect(el.getAttribute("data-state")).toBe("tripped");
    expect(el.textContent).toMatch(/breaker tripped/i);
  });

  // The case the panel exists for: one un-computable row blocks every symbol,
  // and without this the halt is indistinguishable from a quiet market.
  it("names the row that is blocking the entire book", () => {
    render(
      <RiskPanel
        risk={{
          ...healthy, book_risk: null, book_risk_pct: null,
          blocker: { ticket: 1936559060, symbol: "EURUSD", source: "position" },
        }}
      />
    );
    const el = screen.getByTestId("risk-breaker-state");
    expect(el.getAttribute("data-state")).toBe("blocked");
    expect(el.textContent).toMatch(/all trading blocked/i);
    expect(el.textContent).toContain("EURUSD");
    expect(el.textContent).toContain("1936559060");
  });

  it("renders an un-anchored day as a dash, not a confident zero", () => {
    render(
      <RiskPanel risk={{ ...healthy, day_anchor: 0, day_pnl: null, day_pnl_pct: null }} />
    );
    expect(screen.getByText(/not yet anchored/i)).toBeInTheDocument();
  });

  it("states the portfolio cap alongside current book risk", () => {
    render(<RiskPanel risk={healthy} />);
    expect(screen.getByText(/portfolio cap 5%/i)).toBeInTheDocument();
  });
});

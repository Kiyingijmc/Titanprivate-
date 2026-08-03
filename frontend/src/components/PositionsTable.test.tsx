import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PositionsTable } from "./PositionsTable";

const pos = [
  {
    ticket: 123,
    symbol: "EURUSD",
    side: "BUY" as const,
    lots: 0.1,
    entry: 1.1,
    sl: 1.09,
    tp: 1.12,
    pnl: 12.5,
    grade: "A+",
    strategy: "silver_bullet",
  },
];

describe("PositionsTable", () => {
  it("renders a BUY row with a profit-tone side chip and a signed pnl", () => {
    render(<PositionsTable positions={pos} onClose={vi.fn()} readOnly />);
    const row = screen.getByText("EURUSD").closest("tr")!;
    expect(row.textContent).toContain("BUY");
    expect(row.textContent).toContain("+12.50");
    const sideChip = screen.getByText("BUY");
    expect(sideChip.getAttribute("data-tone")).toBe("profit");
  });

  it("close disabled in read-only, fires callback otherwise", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<PositionsTable positions={pos} onClose={onClose} readOnly />);
    expect(screen.getByRole("button", { name: /close/i })).toBeDisabled();

    rerender(<PositionsTable positions={pos} onClose={onClose} readOnly={false} />);
    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledWith(123);
  });

  it("badges a symbol that news is holding", () => {
    render(
      <PositionsTable
        positions={pos}
        onClose={vi.fn()}
        readOnly
        blockedSymbols={{ [pos[0].symbol]: "USD CPI in 20m" }}
      />
    );
    expect(screen.getByTestId("news-blocked-badge")).toBeInTheDocument();
  });

  it("shows no badge when the symbol is not blocked", () => {
    render(<PositionsTable positions={pos} onClose={vi.fn()} readOnly blockedSymbols={{}} />);
    expect(screen.queryByTestId("news-blocked-badge")).toBeNull();
  });

  it("shows no badge when blockedSymbols is omitted", () => {
    render(<PositionsTable positions={pos} onClose={vi.fn()} readOnly />);
    expect(screen.queryByTestId("news-blocked-badge")).toBeNull();
  });
});

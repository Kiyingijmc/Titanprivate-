import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PendingOrdersTable } from "./PendingOrdersTable";
import type { PendingOrder } from "@/lib/types";

const tracked: PendingOrder = {
  ticket: 1939200606, symbol: "ETHUSD", side: "BUY", kind: "LIMIT",
  lots: 0.03, price: 1855.3, sl: 1844.18, tp: 1877.53,
  grade: "B", strategy: "SilverBullet", tracked: true,
};

const orphan: PendingOrder = {
  ticket: 1936559060, symbol: "EURUSD", side: "SELL", kind: "LIMIT",
  lots: 0.15, price: 1.15718, sl: 0, tp: 0,
  grade: "", strategy: "", tracked: false,
};

describe("PendingOrdersTable", () => {
  it("renders a Titan-placed order with its stop, grade and strategy", () => {
    render(<PendingOrdersTable orders={[tracked]} onCancel={() => {}} readOnly={false} />);
    const row = screen.getByTestId("pending-row-1939200606");
    expect(row.textContent).toContain("ETHUSD");
    expect(row.textContent).toContain("1,844.18");
    expect(row.textContent).toContain("B");
    expect(row.textContent).toContain("SilverBullet");
    expect(row.getAttribute("data-tracked")).toBe("true");
  });

  // The reason this table exists. An order with no state-DB row carries no stop
  // the portfolio cap can price, so aggregate_open_risk does not count it — that
  // is real exposure the cap is blind to and it must not look routine.
  it("marks an untracked order and never prints its absent stop as 0", () => {
    render(<PendingOrdersTable orders={[orphan]} onCancel={() => {}} readOnly={false} />);
    const row = screen.getByTestId("pending-row-1936559060");
    expect(screen.getByTestId("untracked-badge-1936559060")).toBeInTheDocument();
    expect(row.getAttribute("data-tracked")).toBe("false");
    expect(row.textContent).toContain("—");
    expect(row.textContent).not.toContain("0.00000");
  });

  it("does not badge a tracked order", () => {
    render(<PendingOrdersTable orders={[tracked]} onCancel={() => {}} readOnly={false} />);
    expect(screen.queryByTestId("untracked-badge-1939200606")).not.toBeInTheDocument();
  });

  it("cancels by ticket", async () => {
    const onCancel = vi.fn();
    render(<PendingOrdersTable orders={[tracked, orphan]} onCancel={onCancel} readOnly={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel order 1936559060" }));
    expect(onCancel).toHaveBeenCalledWith(1936559060);
  });

  it("disables cancel in read-only mode", () => {
    render(<PendingOrdersTable orders={[tracked]} onCancel={() => {}} readOnly />);
    expect(screen.getByRole("button", { name: "Cancel order 1939200606" })).toBeDisabled();
  });

  it("renders stop orders and an unknown type without crashing", () => {
    const stop: PendingOrder = { ...tracked, ticket: 5, kind: "STOP" };
    const unknown: PendingOrder = { ...orphan, ticket: 6, side: "?", kind: "?" };
    render(<PendingOrdersTable orders={[stop, unknown]} onCancel={() => {}} readOnly={false} />);
    expect(screen.getByTestId("pending-row-5").textContent).toContain("STOP");
    expect(screen.getByTestId("pending-row-6")).toBeInTheDocument();
  });
});

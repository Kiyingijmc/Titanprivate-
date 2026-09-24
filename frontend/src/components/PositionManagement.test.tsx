import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PositionDetails, PositionSummary } from "./PositionManagement";
import type { Position } from "@/lib/types";

const position: Position = {
  ticket: 7, symbol: "EURUSD", side: "BUY", lots: .065, entry: 1.1, sl: 1.09, tp: 1.11,
  pnl: 12, grade: "A", strategy: "SilverBullet",
  management: { mode: "m15_structure_v1", confirmed_level: 2, confirmed_partial_stage: 1,
    pending: true, requested_sl: 1.104, requested_tp: 0, target_volume: .049,
    original_tp: 1.11, progress_pct: 60, first_partial_pct: 50, context_ready: false, context_closed_at: null },
};

describe("Position management", () => {
  it("separates broker stops from requested changes and preserves fine volume steps", async () => {
    render(<PositionDetails position={position} />);
    await userEvent.click(screen.getByRole("button", { name: "Inspect position 7" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("1.09")).toBeInTheDocument();
    expect(within(dialog).getByText("1.104")).toBeInTheDocument();
    expect(within(dialog).getByText("0.065 lots")).toBeInTheDocument();
    expect(within(dialog).getByText("0.049 lots")).toBeInTheDocument();
    expect(within(dialog).getByText(/not confirmed executions/)).toBeInTheDocument();
    expect(within(dialog).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "60");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect position 7" })).toHaveFocus();
  });

  it("keeps unavailable progress distinct from zero and shows delayed data", async () => {
    render(<PositionDetails position={{ ...position, management: null }} stale />);
    await userEvent.click(screen.getByRole("button", { name: "Inspect position 7" }));
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Data may be delayed");
  });

  it("does not label a missing TP as an active runner or imply unavailable management is confirmed", async () => {
    const unknown = { ...position, tp: 0, management: null };
    render(<><PositionSummary positions={[unknown]} loading={false} stale={false} /><PositionDetails position={unknown} /></>);
    expect(screen.getByText(/1 with unavailable management status/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Inspect position 7" }));
    expect(screen.getByText("No fixed TP")).toBeInTheDocument();
  });
});

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { ControllerProvider } from "@/context/ControllerContext";
import type { Snapshot } from "@/lib/types";
import type { Api } from "@/lib/api";
import PositionsPage from "./PositionsPage";

function makeSnapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    health: { bridge_connected: true, last_heartbeat_age_s: 2, paused: false, last_error: null },
    account: { balance: 10000, equity: 10250.5 },
    positions: [
      { ticket: 1, symbol: "EURUSD", side: "BUY", lots: 0.1, entry: 1.085, sl: 1.08, tp: 1.09, pnl: 25, grade: "A", strategy: "silver_bullet" },
      { ticket: 2, symbol: "EURUSD", side: "BUY", lots: 0.2, entry: 1.086, sl: 1.081, tp: 1.091, pnl: -10, grade: "B", strategy: "silver_bullet" },
      { ticket: 3, symbol: "XAUUSD", side: "SELL", lots: 0.3, entry: 2400, sl: 2410, tp: 2380, pnl: 40, grade: "A+", strategy: "silver_bullet" },
    ],
    arbiter: { stats: { submitted: 4, approved: 3, blocked_by: { opposition: 1 } }, throttle: { enabled: false, current_mult: 1 } },
    registry: [],
    ...overrides,
  };
}

function fakeApi(): Api {
  return {
    getState: vi.fn(),
    getEvents: vi.fn(),
    getHistory: vi.fn(),
    getSettings: vi.fn(),
    getRegistry: vi.fn(),
    postCommand: vi.fn().mockResolvedValue({ status: "ok" }),
    patchSetting: vi.fn(),
    registryAction: vi.fn(),
  } as unknown as Api;
}

function renderPage({
  snapshot = makeSnapshot(),
  api = fakeApi(),
}: { snapshot?: Snapshot | null; api?: Api } = {}) {
  function Wrapper() {
    return (
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider
            value={{
              snapshot,
              events: [],
              connectionStatus: { status: "live", stale: false },
              api,
            }}
          >
            <PositionsPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );
  }
  const utils = render(<Wrapper />);
  return { ...utils, api };
}

// read-only rendering needs the ReadOnlyProvider to already be flipped; since
// ReadOnlyProvider owns its own state, drive it via a rejected postCommand call
// in the relevant test instead of a prop.

describe("PositionsPage", () => {
  it("shows all 3 positions with no filter applied", async () => {
    renderPage();
    const rows = await screen.findAllByRole("row");
    // header row + 3 data rows
    expect(rows.length).toBe(4);
  });

  it("filtering by symbol 'XAU' shows only the SELL row; clearing shows all 3", async () => {
    renderPage();
    const symbolInput = await screen.findByLabelText(/symbol/i);
    await userEvent.type(symbolInput, "XAU");

    let rows = await screen.findAllByRole("row");
    expect(rows.length).toBe(2); // header + 1
    expect(screen.getByText("XAUUSD")).toBeInTheDocument();
    expect(screen.queryByText("EURUSD")).not.toBeInTheDocument();

    await userEvent.clear(symbolInput);
    rows = await screen.findAllByRole("row");
    expect(rows.length).toBe(4);
  });

  it("side filter BUY shows 2 rows", async () => {
    renderPage();
    const sideSelect = await screen.findByLabelText(/side/i);
    await userEvent.selectOptions(sideSelect, "BUY");

    const rows = await screen.findAllByRole("row");
    expect(rows.length).toBe(3); // header + 2 BUY rows
  });

  it("shows 'No open positions' when positions is empty", async () => {
    renderPage({ snapshot: { ...makeSnapshot(), positions: [] } });
    expect(await screen.findByText(/no open positions/i)).toBeInTheDocument();
  });

  it("shows loading state before the first snapshot arrives", () => {
    renderPage({ snapshot: null });
    expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
  });

  it("per-row close (not read-only): confirm dialog then postCommand({command:'close', ticket})", async () => {
    const { api } = renderPage();
    // default sort is pnl desc, so ticket 3 (pnl 40) renders first
    const closeBtn = await screen.findByRole("button", { name: /close position 3/i });
    await userEvent.click(closeBtn);

    const confirmBtn = await screen.findByRole("button", { name: /confirm/i });
    await userEvent.click(confirmBtn);

    expect(api.postCommand).toHaveBeenCalledWith({ command: "close", ticket: 3 });
  });

  it("Close All (confirm) routes postCommand({command:'closeall', confirm:true})", async () => {
    const { api } = renderPage();
    const closeAllBtn = await screen.findByRole("button", { name: /close all/i });
    await userEvent.click(closeAllBtn);

    const confirmBtn = await screen.findByRole("button", { name: /confirm/i });
    await userEvent.click(confirmBtn);

    expect(api.postCommand).toHaveBeenCalledWith({ command: "closeall", confirm: true });
  });

  it("disables per-row close and Close All once read-only is true (403 flips it)", async () => {
    const api = fakeApi();
    (api.postCommand as any).mockRejectedValue({ status: 403, kind: "readOnly", detail: "read only" });

    renderPage({ api });

    const closeAllBtn = await screen.findByRole("button", { name: /close all/i });
    await userEvent.click(closeAllBtn);
    const confirmBtn = await screen.findByRole("button", { name: /confirm/i });
    await userEvent.click(confirmBtn);

    // after the 403, read-only flips true and the buttons re-render disabled
    const closeButtons = await screen.findAllByRole("button", { name: /close position/i });
    closeButtons.forEach((b) => expect(b).toBeDisabled());
    expect(await screen.findByRole("button", { name: /close all/i })).toBeDisabled();
  });
});

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { ControllerProvider } from "@/context/ControllerContext";
import type { Snapshot, FeedEvent } from "@/lib/types";
import type { Api } from "@/lib/api";
import OverviewPage from "./OverviewPage";

// Freeze the clock the market widgets read. 2026-07-29 13:00 UTC (Wednesday,
// not a weekend) has London + New York open, so session chips render.
vi.mock("@/lib/useNow", () => ({ useNow: () => new Date("2026-07-29T13:00:00Z") }));

function makeSnapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    health: { bridge_connected: true, last_heartbeat_age_s: 2, paused: false, last_error: null },
    account: { balance: 10000, equity: 10250.5 },
    positions: [
      { ticket: 1, symbol: "EURUSD", side: "BUY", lots: 0.1, entry: 1.085, sl: 1.08, tp: 1.09, pnl: 25, grade: "A", strategy: "silver_bullet" },
      { ticket: 2, symbol: "XAUUSD", side: "SELL", lots: 0.2, entry: 2400, sl: 2410, tp: 2380, pnl: -40, grade: "B", strategy: "silver_bullet" },
    ],
    arbiter: { stats: { submitted: 4, approved: 3, blocked_by: { opposition: 1 } }, throttle: { enabled: false, current_mult: 1 } },
    registry: [],
    ...overrides,
  };
}

const events: FeedEvent[] = [
  { topic: "Execution", ts: 1000, symbol: "EURUSD" },
  { topic: "IntentBlocked", ts: 1001, rule: "opposition" },
];

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

function renderOverview({
  snapshot = makeSnapshot(),
}: { snapshot?: Snapshot | null } = {}) {
  const api = fakeApi();

  return render(
    <MemoryRouter>
      <ReadOnlyProvider>
        <ControllerProvider
          value={{
            snapshot,
            events,
            connectionStatus: { status: "live", stale: false },
            api,
          }}
        >
          <OverviewPage />
        </ControllerProvider>
      </ReadOnlyProvider>
    </MemoryRouter>
  );
}

describe("OverviewPage", () => {
  it("renders the KPI equity value from the snapshot", async () => {
    renderOverview();
    expect(await screen.findByText("10,250.50")).toBeInTheDocument();
  });

  it("shows a top-position symbol linking to /positions", async () => {
    renderOverview();
    const link = await screen.findByRole("link", { name: /XAUUSD/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/positions"));
  });

  it("shows a recent-activity event topic linking to /activity", async () => {
    renderOverview();
    const link = await screen.findByRole("link", { name: /IntentBlocked/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/activity"));
  });

  it("disables the Controls buttons once read-only is true", async () => {
    const api = fakeApi();
    (api.postCommand as any).mockRejectedValue({ status: 403, kind: "readOnly", detail: "read only" });

    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider
            value={{
              snapshot: makeSnapshot(),
              events,
              connectionStatus: { status: "live", stale: false },
              api,
            }}
          >
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    const pauseBtn = await screen.findByRole("button", { name: /^pause$/i });
    await userEvent.click(pauseBtn);

    // wait for the async rejection -> onResult({readOnly:true}) -> setReadOnly(true) -> re-render disables all buttons
    await waitFor(async () => {
      const buttons = await screen.findAllByRole("button");
      expect(buttons.length).toBeGreaterThan(0);
      buttons.forEach((b) => expect(b).toBeDisabled());
    });
  });

  it("shows empty states when there are no positions or events", async () => {
    renderOverview({ snapshot: { ...makeSnapshot(), positions: [] } });
    expect(await screen.findByText(/no open positions/i)).toBeInTheDocument();
  });

  it("shows loading state before the first snapshot arrives", () => {
    renderOverview({ snapshot: null });
    expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
  });

  it("renders the top Market Context strip with sessions and the dollar bias", async () => {
    renderOverview({
      snapshot: makeSnapshot({
        dollar: { source: "computed", value: null, bias: 33, trend: [10, 20, 33], contributors: [] },
      }),
    });
    // Full MarketSessions renders session labels; London is open at the mocked instant.
    expect(await screen.findByText("London")).toBeInTheDocument();
    // Full DollarBias widget renders on the page.
    expect(screen.getAllByTestId("dollar-bias").length).toBeGreaterThan(0);
    expect(screen.getByText(/33/)).toBeInTheDocument();
  });
});

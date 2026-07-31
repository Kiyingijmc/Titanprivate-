import { describe, it, expect, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { ControllerProvider } from "@/context/ControllerContext";
import { EquitySparkline } from "@/components/EquitySparkline";
import type { Snapshot, FeedEvent, EquitySeries } from "@/lib/types";
import type { Api } from "@/lib/api";
import OverviewPage, { withLiveTail } from "./OverviewPage";

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

function makeEquitySeries(range: string): EquitySeries {
  return {
    range,
    tier: "coarse",
    bucket_s: 300,
    series: ["equity", "balance", "peak"],
    points: [{ ts: 1000, equity: 10250.5, balance: 10000, peak: 10300 }],
    coverage: { first_sample_ts: 500, n: 1, series_first_ts: {}, gaps: [] },
  };
}

function fakeApi(): Api {
  return {
    getState: vi.fn(),
    getEvents: vi.fn(),
    getHistory: vi.fn(),
    getEquity: vi.fn((range: string) => Promise.resolve(makeEquitySeries(range))),
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
    // The equity value also appears in the equity chart's current-value label, so
    // scope the KPI assertion to the Equity tile specifically.
    const tile = await screen.findByTestId("tile-equity");
    expect(within(tile).getByText("10,250.50")).toBeInTheDocument();
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

  it("shows loading state before the first snapshot arrives", async () => {
    renderOverview({ snapshot: null });
    expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
    // The equity fetch (independent of `snapshot`) still resolves in the
    // background; flush it under `act` so its state update doesn't land after
    // the test has already returned.
    await act(async () => {});
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

  it("shows the range selector defaulted to 1d and swaps the series when a range is picked", async () => {
    const api = fakeApi();

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

    // 1. the selector is present, defaulted to 1d
    const selector = await screen.findByTestId("range-selector");
    await waitFor(() => expect(api.getEquity).toHaveBeenCalledWith("1d"));
    expect(within(selector).getByRole("radio", { name: "1d" })).toHaveAttribute("aria-checked", "true");

    // 2. click "4h" (wait for it to unlock — the selector only enables ranges the
    // fetched coverage actually reaches, which lands one tick after mount)
    const fourHour = within(selector).getByRole("radio", { name: "4h" });
    await waitFor(() => expect(fourHour).not.toBeDisabled());
    await userEvent.click(fourHour);

    // 3. the fetch was re-issued for the newly picked range
    await waitFor(() => expect(api.getEquity).toHaveBeenCalledWith("4h"));
  });
});

function fineSeries(overrides: Partial<EquitySeries> = {}): EquitySeries {
  return {
    range: "4h",
    tier: "fine",
    bucket_s: 30,
    series: ["equity", "balance", "peak"],
    points: [
      { ts: 1000, equity: 10000, balance: 9990, peak: 10000 },
      { ts: 1030, equity: 10010, balance: 9990, peak: 10010 },
    ],
    coverage: { first_sample_ts: 1000, n: 2, series_first_ts: {}, gaps: [] },
    ...overrides,
  };
}

describe("withLiveTail", () => {
  it("appends a live tail point strictly newer than the series' last real ts", () => {
    const series = fineSeries();
    const merged = withLiveTail(series, [{ ts: 1060, equity: 10020 }]);
    expect(merged!.points).toHaveLength(3);
    expect(merged!.points[2]).toEqual({ ts: 1060, equity: 10020, balance: 9990, peak: 10020 });
  });

  it("drops a tail point at or before the series' last real ts (no double-counting the same instant)", () => {
    const series = fineSeries();
    const atLastTs = withLiveTail(series, [{ ts: 1030, equity: 99999 }]);
    expect(atLastTs!.points).toHaveLength(2); // unchanged — same instant already represented

    const beforeLastTs = withLiveTail(series, [{ ts: 900, equity: 99999 }]);
    expect(beforeLastTs!.points).toHaveLength(2);
  });

  it("leaves a coarse range untouched — a bucketed line must not sprout a high-res spike", () => {
    const series = fineSeries({ range: "1d", tier: "coarse", bucket_s: 300 });
    const merged = withLiveTail(series, [{ ts: 1060, equity: 10020 }]);
    expect(merged).toBe(series); // same reference — nothing appended, nothing copied
  });

  it("keeps points ascending in ts — appended tail points cannot reorder the series", () => {
    const series = fineSeries();
    // fed out of order; the merge must sort the fresh tail before appending
    const merged = withLiveTail(series, [
      { ts: 1090, equity: 10040 },
      { ts: 1060, equity: 10020 },
    ]);
    const tsValues = merged!.points.map((p) => p!.ts);
    expect(tsValues).toEqual([...tsValues].sort((a, b) => a - b));
  });

  it("the augmented series still renders", () => {
    const series = fineSeries();
    const merged = withLiveTail(series, [{ ts: 1060, equity: 10020 }]);
    render(<EquitySparkline points={[]} series={merged!} width={400} height={200} />);
    expect(screen.getByTestId("equity-sparkline")).toBeInTheDocument();
  });
});

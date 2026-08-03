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

/**
 * A realistic `/api/equity` payload: timestamps sit on the SERVER clock near
 * "now" and ten days of history precede them. This is deliberately built from
 * `Date.now()` rather than fixed constants — since the panel anchors range
 * gating to server time (derived from the newest sample), a fixture with epoch
 * timestamps in 1970 correctly reports "10 minutes of history" and unlocks
 * nothing. The old constant fixture only unlocked ranges because the code was
 * comparing a 2026 browser clock against a 1970 server one.
 */
function makeEquitySeries(range: string): EquitySeries {
  const nowS = Math.floor(Date.now() / 1000);
  return {
    range,
    tier: "coarse",
    bucket_s: 300,
    series: ["equity", "balance", "peak"],
    points: [{ ts: nowS - 60, equity: 10250.5, balance: 10000, peak: 10300 }],
    coverage: { first_sample_ts: nowS - 10 * 86400, n: 1, series_first_ts: {}, gaps: [] },
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
    // Scoped to the Controls panel itself: the page also carries a "Maximize
    // Equity" button (Panel.onMaximize) which is presentational, not a write
    // command, and is correctly NOT gated by read-only.
    await waitFor(async () => {
      const controlsHeading = screen.getByRole("heading", { name: "Controls" });
      const controlsPanel = controlsHeading.parentElement!.parentElement as HTMLElement;
      const buttons = within(controlsPanel).getAllByRole("button");
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

  it("renders the NewsPanel when the snapshot carries a news block", async () => {
    renderOverview({
      snapshot: makeSnapshot({
        news: { status: "ok", cache_age_min: 5, next: null, blocked_symbols: {} },
      }),
    });
    expect(await screen.findByTestId("news-panel")).toBeInTheDocument();
  });

  it("still renders the NewsPanel (in its unavailable state) when snapshot.news is undefined", async () => {
    renderOverview();
    expect(await screen.findByTestId("news-panel")).toBeInTheDocument();
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

  // ---- C1: a dead /api/equity must not render as a healthy frozen chart ----

  it("shows a VISIBLE refresh-failure badge when a poll fails but the last series is still on screen", async () => {
    // The recorder's SQLite goes read-locked while the WS heartbeat stays
    // healthy: `useEquitySeries` keeps the last good data (correctly), `loading`
    // is cleared by its `finally` even on the failure path, and the Panel's
    // status comes from the WS snapshot — so without this the operator sees a
    // confident, undimmed, hours-old curve.
    const api = fakeApi();
    (api.getEquity as any)
      .mockResolvedValueOnce(makeEquitySeries("1d"))
      .mockRejectedValue({ status: 500, kind: "error", detail: "database is locked" });

    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}>
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    // First fetch succeeds; the next one (triggered by a range change, exactly
    // as a poll tick would) fails while the last good series stays on screen.
    const selector = await screen.findByTestId("range-selector");
    const fourHour = within(selector).getByRole("radio", { name: "4h" });
    await waitFor(() => expect(fourHour).not.toBeDisabled());
    await userEvent.click(fourHour);

    const badge = await screen.findByTestId("equity-fetch-error");
    // Visible to a sighted user — real text nodes, not an aria-label.
    expect(badge).toHaveTextContent(/could not be refreshed/i);
    expect(badge).toHaveTextContent(/database is locked/i);
    // ...and the chart it labels is still there (we keep the last good curve).
    expect(screen.getByTestId("equity-sparkline")).toBeInTheDocument();
  });

  it("distinguishes 'could not load' from 'nothing recorded' when the FIRST fetch fails", async () => {
    // firstSampleTs is null in both cases, but only one of them is a claim about
    // the RECORDER. Asserting "No equity history recorded yet" from a network
    // failure is a confident wrong statement about the trading system.
    const api = fakeApi();
    (api.getEquity as any).mockRejectedValue({ status: 503, kind: "error", detail: "bridge down" });

    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}>
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    // Re-query every time: the Panel re-wraps its children when its status flips
    // to "stale", so a node captured before the failure is detached.
    const dayRadio = () => within(screen.getByTestId("range-selector")).getByRole("radio", { name: "1d" });
    await screen.findByTestId("range-selector");
    await waitFor(() =>
      expect(dayRadio()).toHaveAttribute("title", expect.stringContaining("Could not load")),
    );
    expect(dayRadio().getAttribute("title")).not.toContain("No equity history recorded yet");
    expect(await screen.findByTestId("equity-fetch-error")).toHaveTextContent(/could not be loaded/i);
  });

  // ---- I2: the chart readout must agree with the KPI tile on the default range ----

  it("on the default 1d range the chart's readout matches the live KPI equity", async () => {
    // The fixture's newest stored bucket is 10,250.50 and the live snapshot is
    // 10,299.00 — different numbers, three inches apart, on the view the
    // operator lands on. The 1d coarse leading point closes the gap.
    const api = fakeApi();
    const tree = (snapshot: Snapshot) => (
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider value={{ snapshot, events, connectionStatus: { status: "live", stale: false }, api }}>
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    const { rerender } = render(tree(makeSnapshot()));
    await screen.findByTestId("range-selector");
    await waitFor(() => expect(api.getEquity).toHaveBeenCalledWith("1d"));

    // A heartbeat lands after the fetch, moving equity off the last stored bucket.
    const moved = makeSnapshot();
    moved.account.equity = 10299;
    rerender(tree(moved));

    const tile = await screen.findByTestId("tile-equity");
    expect(within(tile).getByText("10,299.00")).toBeInTheDocument();
    const chart = screen.getByTestId("equity-sparkline");
    await waitFor(() => expect(within(chart).getByText("10,299.00")).toBeInTheDocument());
    // and the default range really is the coarse one this used to bail out on
    expect(await screen.findByTestId("equity-delta-basis")).toHaveTextContent("1d");
  });

  // ---- I3: the delta's basis is labelled, visibly ----

  it("labels the delta's basis so it cannot silently change meaning on first fetch", async () => {
    renderOverview();
    // Before the fetch lands the legacy buffer path renders, whose delta means
    // "since this tab opened"...
    expect(await screen.findByTestId("equity-delta-basis")).toHaveTextContent("session");
    // ...and once the series lands the SAME glyph means "across the 1d window".
    // Re-query: the two paths are different elements, not one mutated node.
    await waitFor(() => expect(screen.getByTestId("equity-delta-basis")).toHaveTextContent("1d"));
  });

  // ---- I5 (page half): the spec'd global [ / ] range shortcuts ----

  it("steps the lookback range with the [ and ] shortcuts", async () => {
    const api = fakeApi();

    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}>
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    const selector = await screen.findByTestId("range-selector");
    await waitFor(() => expect(within(selector).getByRole("radio", { name: "12h" })).not.toBeDisabled());

    await userEvent.keyboard("[[");
    await waitFor(() => expect(within(selector).getByRole("radio", { name: "12h" })).toHaveAttribute("aria-checked", "true"));

    await userEvent.keyboard("]");
    await waitFor(() => expect(within(selector).getByRole("radio", { name: "1d" })).toHaveAttribute("aria-checked", "true"));
  });

  it("ignores [ and ] while the operator is typing", async () => {
    const api = fakeApi();

    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}>
            <OverviewPage />
            <input aria-label="scratch" />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    const selector = await screen.findByTestId("range-selector");
    await waitFor(() => expect(within(selector).getByRole("radio", { name: "12h" })).not.toBeDisabled());

    const input = screen.getByLabelText("scratch");
    await userEvent.click(input);
    await userEvent.keyboard("[[");
    expect(input).toHaveValue("[");
    expect(within(selector).getByRole("radio", { name: "1d" })).toHaveAttribute("aria-checked", "true");
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
  // The tail is stamped on the BROWSER clock; the series' ts values come from
  // the server's SQLite. `serverOffset` is what reconciles them. offset 0 means
  // the two clocks happen to agree.
  it("appends a live tail point strictly newer than the series' last real ts", () => {
    const series = fineSeries();
    const merged = withLiveTail(series, [{ clientTs: 1060, equity: 10020 }], 0);
    expect(merged!.points).toHaveLength(3);
    expect(merged!.points[2]).toEqual({ ts: 1060, equity: 10020, balance: 9990, peak: 10020 });
  });

  it("drops a tail point at or before the series' last real ts (no double-counting the same instant)", () => {
    const series = fineSeries();
    const atLastTs = withLiveTail(series, [{ clientTs: 1030, equity: 99999 }], 0);
    expect(atLastTs!.points).toHaveLength(2); // unchanged — same instant already represented

    const beforeLastTs = withLiveTail(series, [{ clientTs: 900, equity: 99999 }], 0);
    expect(beforeLastTs!.points).toHaveLength(2);
  });

  it("keeps points ascending in ts — appended tail points cannot reorder the series", () => {
    const series = fineSeries();
    // fed out of order; the merge must sort the fresh tail before appending
    const merged = withLiveTail(series, [
      { clientTs: 1090, equity: 10040 },
      { clientTs: 1060, equity: 10020 },
    ], 0);
    const tsValues = merged!.points.map((p) => p!.ts);
    expect(tsValues).toEqual([...tsValues].sort((a, b) => a - b));
  });

  it("the augmented series still renders", () => {
    const series = fineSeries();
    const merged = withLiveTail(series, [{ clientTs: 1060, equity: 10020 }], 0);
    render(<EquitySparkline points={[]} series={merged!} width={400} height={200} />);
    expect(screen.getByTestId("equity-sparkline")).toBeInTheDocument();
  });

  // ---- I1: two clocks on one axis ----

  describe("client clock skew", () => {
    it("still renders the tail when the CLIENT clock is behind the server", () => {
      // Client is 10 minutes slow: its raw stamps (450, 460) are far BELOW the
      // server's last real ts of 1030, so an unreconciled `t.ts > lastReal.ts`
      // drops every point and the tail silently never appears — no error, no
      // empty state, just a leading edge that stopped moving.
      const series = fineSeries();
      const skew = -600;
      const naive = withLiveTail(series, [{ clientTs: 1060 + skew, equity: 10020 }], 0);
      expect(naive!.points).toHaveLength(2); // the bug, reproduced with offset 0

      const merged = withLiveTail(series, [{ clientTs: 1060 + skew, equity: 10020 }], -skew);
      expect(merged!.points).toHaveLength(3);
      expect(merged!.points[2]!.ts).toBe(1060);
    });

    it("does not plot the tail in the future when the CLIENT clock is ahead of the server", () => {
      // Client is an hour fast. Untranslated, its point lands at 4660 — 1h past
      // the newest real sample — stretching the ["dataMin","dataMax"] domain and
      // drawing a long flat lead-out that reads as recorded data.
      const series = fineSeries();
      const skew = 3600;
      const naive = withLiveTail(series, [{ clientTs: 1060 + skew, equity: 10020 }], 0);
      expect(naive!.points.at(-1)!.ts).toBe(4660);

      const merged = withLiveTail(series, [{ clientTs: 1060 + skew, equity: 10020 }], -skew);
      expect(merged!.points.at(-1)!.ts).toBe(1060);
      // and it stays within a plausible distance of the server's own newest sample
      expect(merged!.points.at(-1)!.ts - 1030).toBeLessThanOrEqual(60);
    });
  });

  // ---- I2: the tail must reach the DEFAULT (coarse 1d) range ----

  describe("tier-appropriate resolution", () => {
    it("fine tier gets the FULL tail", () => {
      const series = fineSeries();
      const merged = withLiveTail(series, [
        { clientTs: 1040, equity: 10011 },
        { clientTs: 1050, equity: 10012 },
        { clientTs: 1060, equity: 10013 },
      ], 0);
      expect(merged!.points).toHaveLength(5); // 2 fetched + 3 tail
    });

    it("coarse 1d gets EXACTLY ONE leading point, not the raw stream", () => {
      // 1d is the default range and is coarse (300s buckets). Shipping
      // fine-tier-only left the chart's readout showing the last flushed bucket
      // while the KPI tile beside it showed live equity. One point fixes the
      // disagreement; three would fabricate 10s resolution on a 300s line.
      const series = fineSeries({ range: "1d", tier: "coarse", bucket_s: 300 });
      const merged = withLiveTail(series, [
        { clientTs: 1040, equity: 10011 },
        { clientTs: 1050, equity: 10012 },
        { clientTs: 1060, equity: 10013 },
      ], 0);
      expect(merged).not.toBe(series);
      expect(merged!.points).toHaveLength(3); // 2 fetched + 1 leading
      const lead = merged!.points[2]!;
      expect(lead.ts).toBe(1060);
      expect(lead.equity).toBe(10013); // current equity, matching the KPI tile
      // peak is the running max over ALL observed samples, not just the drawn one
      expect(lead.peak).toBe(10013);
    });

    it("ranges wider than a day are left untouched", () => {
      for (const range of ["1w", "1mo", "1y"]) {
        const series = fineSeries({ range, tier: "coarse", bucket_s: 3600 });
        const merged = withLiveTail(series, [{ clientTs: 1060, equity: 10020 }], 0);
        expect(merged).toBe(series); // same reference — nothing appended, nothing copied
      }
    });

    it("an unrecognised range name is treated as too wide to tail (fail closed)", () => {
      const series = fineSeries({ range: "5y", tier: "coarse", bucket_s: 3600 });
      expect(withLiveTail(series, [{ clientTs: 1060, equity: 10020 }], 0)).toBe(series);
    });
  });

  // ---- M6: the tail is bounded in TIME, not only in count ----

  it("clamps the tail to the selected range's window during a poll outage", () => {
    // /api/equity is down: the fetched block is frozen at ts 1030 while the WS
    // keeps delivering. A count-only bound (300 points) let a chart labelled
    // "15m" quietly accumulate hours of live samples.
    const series = fineSeries({ range: "15m" });
    const tail = Array.from({ length: 200 }, (_, i) => ({
      clientTs: 1040 + i * 30,     // 200 samples * 30s = ~100 minutes
      equity: 10010 + i,
    }));
    const merged = withLiveTail(series, tail, 0);
    const tsValues = merged!.points.map((p) => p!.ts);
    const appended = tsValues.slice(2);
    expect(appended.length).toBeGreaterThan(0);
    expect(appended[appended.length - 1] - appended[0]).toBeLessThanOrEqual(900);
  });
});

describe("equity maximize", () => {
  it("keeps exactly one chart and one range selector when maximized", async () => {
    renderOverview();

    await screen.findByTestId("range-selector");
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));

    expect(await screen.findByRole("dialog", { name: "Equity" })).toBeInTheDocument();
    // The collapsed body must go quiet: duplicates break single-match queries
    // used all over this file, and would announce twice to assistive tech.
    expect(screen.getAllByTestId("equity-sparkline")).toHaveLength(1);
    expect(screen.getAllByTestId("range-selector")).toHaveLength(1);
  });

  it("still switches range from inside the maximized view", async () => {
    const api = fakeApi();
    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider
            value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}
          >
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    await screen.findByTestId("range-selector");
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));

    const selector = await screen.findByTestId("range-selector");
    const fourHour = within(selector).getByRole("radio", { name: "4h" });
    await waitFor(() => expect(fourHour).not.toBeDisabled());
    await userEvent.click(fourHour);

    await waitFor(() => expect(api.getEquity).toHaveBeenCalledWith("4h"));
  });

  it("surfaces a fetch failure inside the maximized view, not only in the card", async () => {
    const api = fakeApi();
    (api.getEquity as any).mockRejectedValue({ status: 503, kind: "error", detail: "bridge down" });
    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider
            value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}
          >
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    await screen.findByTestId("equity-fetch-error");
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));

    const dialog = await screen.findByRole("dialog", { name: "Equity" });
    expect(within(dialog).getByTestId("equity-fetch-error")).toBeInTheDocument();
    expect(screen.getAllByTestId("equity-fetch-error")).toHaveLength(1);
  });

  it("closes on Escape and returns focus to the maximize button", async () => {
    renderOverview();
    await screen.findByTestId("range-selector");

    const button = screen.getByRole("button", { name: "Maximize Equity" });
    await userEvent.click(button);
    await screen.findByRole("dialog", { name: "Equity" });

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(button).toHaveFocus());
  });
});

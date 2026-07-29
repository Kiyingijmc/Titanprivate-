import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ControllerProvider } from "@/context/ControllerContext";
import type { FeedEvent } from "@/lib/types";
import type { Api } from "@/lib/api";
import ActivityPage from "./ActivityPage";

function fakeApi(): Api {
  return {
    getState: () => Promise.resolve({} as never),
    getEvents: () => Promise.resolve([]),
    getHistory: () => Promise.resolve([]),
    getSettings: () => Promise.resolve([]),
    getRegistry: () => Promise.resolve([]),
    postCommand: () => Promise.resolve({ status: "ok" }),
    patchSetting: () => Promise.resolve({}),
    registryAction: () => Promise.resolve({ status: "ok" }),
  } as unknown as Api;
}

const EVENTS: FeedEvent[] = [
  { topic: "Heartbeat", ts: 1720000001 },
  { topic: "IntentEmitted", ts: 1720000002, symbol: "EURUSD" },
  { topic: "IntentBlocked", ts: 1720000003, rule: "opposition", symbol: "EURUSD" },
  { topic: "EXECUTION", ts: 1720000004, type: "CLOSED", symbol: "XAUUSD", ticket: 42 },
  { topic: "SystemStateChanged", ts: 1720000005, state: "paused" },
];

// jsdom has no layout engine, so useVirtualizer's measured container size is 0.
// With overscan (8) larger than this small fixture (5 rows), the virtualizer's
// range still expands to cover every row regardless of measured height, so no
// extra container-height mocking is needed for these assertions.
function renderPage(events: FeedEvent[] = EVENTS) {
  return render(
    <MemoryRouter>
      <ControllerProvider
        value={{
          snapshot: null,
          events,
          connectionStatus: { status: "live", stale: false },
          api: fakeApi(),
        }}
      >
        <ActivityPage />
      </ControllerProvider>
    </MemoryRouter>
  );
}

describe("ActivityPage", () => {
  it("renders the IntentBlocked violet rule chip", () => {
    renderPage();
    const chip = screen.getByText("opposition");
    expect(chip.className).toContain("text-blocked");
  });

  it("filtering to IntentBlocked hides the execution row and keeps IntentBlocked", async () => {
    renderPage();
    const select = screen.getByLabelText(/event type/i);
    await userEvent.selectOptions(select, "IntentBlocked");

    expect(screen.getByText("opposition")).toBeInTheDocument();
    expect(screen.queryByText(/42/)).not.toBeInTheDocument();
  });

  it("shows 'No events yet' when there are no events", () => {
    renderPage([]);
    expect(screen.getByText(/no events yet/i)).toBeInTheDocument();
  });
});

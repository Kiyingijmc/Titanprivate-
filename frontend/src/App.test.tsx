import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Snapshot } from "@/lib/types";

// The shell renders two nav landmarks (sidebar "Sections" + phone "Primary"/BottomTabs);
// scope link queries to the sidebar so the responsive duplication isn't ambiguous.
const sidebar = () => within(screen.getByRole("navigation", { name: "Sections" }));

// jsdom has no scrollIntoView; cmdk (used by CommandPalette) calls it on selection-change.
if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = () => {};
}

const seededSnapshot: Snapshot = {
  health: { bridge_connected: true, last_heartbeat_age_s: 3, paused: false, last_error: null },
  account: { balance: 10000, equity: 10250 },
  positions: [
    {
      ticket: 555,
      symbol: "EURUSD",
      side: "BUY",
      lots: 0.1,
      entry: 1.085,
      sl: 1.08,
      tp: 1.09,
      pnl: 25,
      grade: "A",
      strategy: "silver_bullet",
    },
  ],
  arbiter: {
    stats: { submitted: 4, approved: 3, blocked_by: { opposition: 1 } },
    throttle: { enabled: false, current_mult: 1 },
  },
  registry: [],
};

vi.mock("@/lib/useLiveState", () => ({
  useLiveState: () => ({
    snapshot: seededSnapshot,
    events: [],
    connected: true,
    connectionStatus: { status: "live", stale: false },
  }),
}));

import App from "./App";

async function connect() {
  render(<App />);
  await userEvent.type(screen.getByLabelText(/token/i), "devtoken");
  await userEvent.click(screen.getByRole("button", { name: /connect/i }));
}

describe("App", () => {
  it("gates on token, then renders the navigable shell with the real Overview page", async () => {
    await connect();

    // Sidebar section links present.
    expect(await screen.findByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(sidebar().getByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(sidebar().getByRole("link", { name: "Positions" })).toBeInTheDocument();

    // Status bar shows the Live connection pill.
    expect(screen.getByText(/live/i)).toBeInTheDocument();

    // Default route (/overview) renders the real Overview page (Plan 2 Task 2): KPI tiles + top-positions panel.
    expect(await screen.findByText("Top Positions")).toBeInTheDocument();
    // "open / pending" — the fixture has one position and no resting orders.
    expect(await screen.findByTestId("tile-open-positions")).toHaveTextContent("1 / 0");
  });

  it("navigates to the real Positions page when the Positions nav link is clicked", async () => {
    await connect();
    await screen.findByRole("navigation", { name: "Sections" });

    await userEvent.click(sidebar().getByRole("link", { name: "Positions" }));

    // The real Positions page (Plan 2 Task 3) renders its filter bar (symbol filter),
    // not the old stub text.
    expect(await screen.findByLabelText(/symbol/i)).toBeInTheDocument();
  });

  it("opens the command palette on Ctrl/Cmd+K", async () => {
    await connect();
    await screen.findByRole("navigation", { name: "Sections" });

    fireEvent.keyDown(document, { key: "k", metaKey: true });

    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeInTheDocument();
  });
});

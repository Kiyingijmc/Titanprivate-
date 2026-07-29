import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Snapshot } from "@/lib/types";

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
  it("gates on token, then renders the navigable shell with the Overview stub", async () => {
    await connect();

    // Sidebar section links present.
    expect(await screen.findByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Positions" })).toBeInTheDocument();

    // Status bar shows the Live connection pill.
    expect(screen.getByText(/live/i)).toBeInTheDocument();

    // Default route (/overview) renders the Overview stub.
    expect(await screen.findByText(/overview.*coming in plan 2/i)).toBeInTheDocument();
  });

  it("navigates to the Positions stub when the Positions nav link is clicked", async () => {
    await connect();
    await screen.findByRole("link", { name: "Overview" });

    await userEvent.click(screen.getByRole("link", { name: "Positions" }));

    expect(await screen.findByText(/positions.*coming in plan 2/i)).toBeInTheDocument();
  });

  it("opens the command palette on Ctrl/Cmd+K", async () => {
    await connect();
    await screen.findByRole("link", { name: "Overview" });

    fireEvent.keyDown(document, { key: "k", metaKey: true });

    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeInTheDocument();
  });
});

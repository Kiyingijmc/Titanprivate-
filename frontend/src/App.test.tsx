import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Snapshot } from "@/lib/types";

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
  useLiveState: () => ({ snapshot: seededSnapshot, events: [], connected: true }),
}));

import App from "./App";

describe("App", () => {
  it("gates on token, then renders the cockpit with a seeded position and health", async () => {
    render(<App />);

    await userEvent.type(screen.getByLabelText(/token/i), "devtoken");
    await userEvent.click(screen.getByRole("button", { name: /connect/i }));

    expect(await screen.findByText("EURUSD")).toBeInTheDocument();
    expect(await screen.findByRole("status", { name: /system health/i })).toBeInTheDocument();
    expect(screen.getByText(/connected/i)).toBeInTheDocument();
  });
});

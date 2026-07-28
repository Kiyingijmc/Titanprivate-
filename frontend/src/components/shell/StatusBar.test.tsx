import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatusBar } from "./StatusBar";
import type { Snapshot } from "@/lib/types";
import type { ConnectionState } from "@/lib/connection";

function makeSnapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    health: { bridge_connected: true, last_heartbeat_age_s: 2, paused: false, last_error: null },
    account: { balance: 10000, equity: 10250.5 },
    positions: [],
    arbiter: { stats: { submitted: 0, approved: 0, blocked_by: {} }, throttle: { enabled: false, current_mult: 1 } },
    registry: [],
    ...overrides,
  };
}

const liveConn: ConnectionState = { status: "live", stale: false };

describe("StatusBar", () => {
  it("renders Degraded for connection.status='degraded'", () => {
    render(
      <StatusBar
        connection={{ status: "degraded", stale: false }}
        snapshot={makeSnapshot()}
        onOpenPalette={() => {}}
      />
    );
    expect(screen.getByText(/degraded/i)).toBeInTheDocument();
  });

  it("shows a Stale marker when connection.stale is true", () => {
    render(
      <StatusBar
        connection={{ status: "live", stale: true }}
        snapshot={makeSnapshot()}
        onOpenPalette={() => {}}
      />
    );
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
  });

  it("shows Paused when snapshot.health.paused is true", () => {
    render(
      <StatusBar
        connection={liveConn}
        snapshot={makeSnapshot({ health: { bridge_connected: true, last_heartbeat_age_s: 1, paused: true, last_error: null } })}
        onOpenPalette={() => {}}
      />
    );
    expect(screen.getByText(/paused/i)).toBeInTheDocument();
  });

  it("shows the throttle multiplier when arbiter.throttle.enabled is true", () => {
    render(
      <StatusBar
        connection={liveConn}
        snapshot={makeSnapshot({
          arbiter: { stats: { submitted: 0, approved: 0, blocked_by: {} }, throttle: { enabled: true, current_mult: 0.5 } },
        })}
        onOpenPalette={() => {}}
      />
    );
    const throttleChip = screen.getByText(/throttle/i);
    expect(throttleChip).toBeInTheDocument();
    expect(throttleChip.closest("span")?.textContent).toMatch(/0\.5/);
  });

  it("calls onOpenPalette when the ⌘K button is clicked", async () => {
    const onOpenPalette = vi.fn();
    render(<StatusBar connection={liveConn} snapshot={makeSnapshot()} onOpenPalette={onOpenPalette} />);
    await userEvent.click(screen.getByRole("button", { name: /command/i }));
    expect(onOpenPalette).toHaveBeenCalledTimes(1);
  });

  it("renders without throwing when snapshot is null, and still shows the connection pill", () => {
    render(<StatusBar connection={liveConn} snapshot={null} onOpenPalette={() => {}} />);
    expect(screen.getByText(/live/i)).toBeInTheDocument();
  });
});

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HealthStrip } from "./HealthStrip";

const arb = { stats: { submitted: 0, approved: 0, blocked_by: {} }, throttle: { enabled: true, current_mult: 0.5 } };

describe("HealthStrip", () => {
  it("shows stale + paused + throttle mult", () => {
    render(<HealthStrip health={{ bridge_connected: false, last_heartbeat_age_s: 120, paused: true, last_error: null }} arbiter={arb} />);
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
    expect(screen.getByText(/paused/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.5/)).toBeInTheDocument();
  });

  it("shows connected when bridge is up and no throttle pill when disabled", () => {
    render(
      <HealthStrip
        health={{ bridge_connected: true, last_heartbeat_age_s: 3, paused: false, last_error: null }}
        arbiter={{ stats: { submitted: 0, approved: 0, blocked_by: {} }, throttle: { enabled: false, current_mult: 1 } }}
      />
    );
    expect(screen.getByText(/connected/i)).toBeInTheDocument();
    expect(screen.queryByText(/throttle/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/paused/i)).not.toBeInTheDocument();
  });
});

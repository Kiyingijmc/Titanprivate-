import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MarketSessions } from "./MarketSessions";

describe("MarketSessions", () => {
  it("shows London and New York as Open during their overlap window", () => {
    // 2026-07-15 14:00 UTC — both London (BST, 07-16 UTC) and New York
    // (EDT, 12-21 UTC) are open; classic London<->NY overlap.
    const now = new Date("2026-07-15T14:00:00Z");
    render(<MarketSessions now={now} />);

    const londonChip = screen.getByTestId("session-chip-london");
    const nyChip = screen.getByTestId("session-chip-newyork");
    expect(within(londonChip).getByText(/open/i)).toBeInTheDocument();
    expect(within(nyChip).getByText(/open/i)).toBeInTheDocument();

    // overlap callout should surface somewhere on the page
    expect(screen.getByText(/overlap/i)).toBeInTheDocument();
  });

  it("shows an 'Opens in' countdown for a session that hasn't opened yet", () => {
    // 2026-07-15 03:00 UTC — Sydney is open (BST offset aside, Sydney's
    // local window is 07-16 local = ~21:00-06:00 UTC in July, AEST no DST),
    // but Tokyo (00:00-09:00 UTC) is open and London hasn't opened yet
    // (London opens 07:00 UTC in July). Assert London shows a countdown.
    const now = new Date("2026-07-15T03:00:00Z");
    render(<MarketSessions now={now} />);
    const londonChip = screen.getByTestId("session-chip-london");
    expect(within(londonChip).getByText(/opens in/i)).toBeInTheDocument();
  });

  it("shows a weekend-closed banner on Saturday", () => {
    const now = new Date("2026-07-18T12:00:00Z"); // Saturday
    render(<MarketSessions now={now} />);
    expect(screen.getByText(/markets closed/i)).toBeInTheDocument();
  });
});

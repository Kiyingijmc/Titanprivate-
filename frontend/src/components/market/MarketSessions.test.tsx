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

  it("shows a weekend-closed banner on Saturday for an FX-only book", () => {
    const now = new Date("2026-07-18T12:00:00Z"); // Saturday
    render(<MarketSessions now={now} />);
    expect(screen.getByText(/markets closed/i)).toBeInTheDocument();
  });

  // Regression for the 2026-08-02 operator report: the card claimed "Markets
  // closed" on a Sunday while the engine was trading ETHUSD, and it rendered a
  // live session-overlap badge on top of that same banner.
  describe("with a 24/7 instrument in the book", () => {
    const sunday = new Date("2026-08-02T07:14:00Z");

    it("keeps the timeline instead of the closed banner", () => {
      render(<MarketSessions now={sunday} hasCrypto />);
      expect(screen.queryByTestId("weekend-closed-banner")).not.toBeInTheDocument();
      expect(screen.getByTestId("session-timeline")).toBeInTheDocument();
    });

    it("explains that FX is shut but the engine is live", () => {
      render(<MarketSessions now={sunday} hasCrypto />);
      expect(screen.getByTestId("crypto-only-note")).toBeInTheDocument();
    });

    it("still shows the closed banner when the book is FX-only", () => {
      render(<MarketSessions now={sunday} hasCrypto={false} />);
      expect(screen.getByTestId("weekend-closed-banner")).toBeInTheDocument();
    });
  });

  it("never shows an overlap badge while FX is closed", () => {
    // Sunday 07:14Z: Tokyo and London both compute as 'open' on their own
    // clocks, so the badge used to render directly above "Markets closed".
    const sunday = new Date("2026-08-02T07:14:00Z");
    render(<MarketSessions now={sunday} />);
    expect(screen.queryByText(/overlap/i)).not.toBeInTheDocument();
  });
});

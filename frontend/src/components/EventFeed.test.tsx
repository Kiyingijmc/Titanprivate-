import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EventFeed } from "./EventFeed";
import type { FeedEvent } from "@/lib/types";

describe("EventFeed", () => {
  it("renders an IntentBlocked event's rule as a violet chip", () => {
    const events: FeedEvent[] = [
      { topic: "IntentBlocked", ts: 1720000000, rule: "opposition", symbol: "EURUSD" },
    ];
    render(<EventFeed events={events} />);
    const chip = screen.getByText("opposition");
    expect(chip.className).toContain("text-blocked");
  });

  it("has an aria-live polite region", () => {
    render(<EventFeed events={[]} />);
    expect(screen.getByRole("log")).toHaveAttribute("aria-live", "polite");
  });

  it("renders events newest-last", () => {
    const events: FeedEvent[] = [
      { topic: "Heartbeat", ts: 1 },
      { topic: "IntentBlocked", ts: 2, rule: "cap" },
    ];
    render(<EventFeed events={events} />);
    const rows = screen.getAllByTestId("event-row");
    expect(rows).toHaveLength(2);
    expect(rows[1].textContent).toContain("cap");
  });
});

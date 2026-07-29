import { describe, it, expect } from "vitest";
import { sessionStates, zoneOffsetMinutes } from "./sessions";

describe("sessions", () => {
  it("london+newyork overlap active during Wed 14:00Z", () => {
    const now = new Date("2026-07-15T14:00:00Z");
    const { sessions, overlaps, activeIds, weekendClosed } = sessionStates(now);
    const london = sessions.find((s) => s.id === "london")!;
    const newyork = sessions.find((s) => s.id === "newyork")!;
    expect(london.open).toBe(true);
    expect(newyork.open).toBe(true);
    const lnOverlap = overlaps.find(
      (o) => o.ids[0] === "london" && o.ids[1] === "newyork",
    )!;
    expect(lnOverlap.active).toBe(true);
    expect(activeIds).toContain("london");
    expect(activeIds).toContain("newyork");
    expect(weekendClosed).toBe(false);
  });

  it("weekendClosed is true on Saturday", () => {
    const now = new Date("2026-07-18T12:00:00Z");
    const { weekendClosed } = sessionStates(now);
    expect(weekendClosed).toBe(true);
  });

  it("london is closed and 'Opens in' before its open time", () => {
    const now = new Date("2026-07-15T02:00:00Z");
    const { sessions } = sessionStates(now);
    const london = sessions.find((s) => s.id === "london")!;
    expect(london.open).toBe(false);
    expect(london.statusLabel.startsWith("Opens in")).toBe(true);
  });

  it("zoneOffsetMinutes is DST-correct for Europe/London", () => {
    expect(zoneOffsetMinutes("Europe/London", new Date("2026-07-15T12:00:00Z"))).toBe(60);
    expect(zoneOffsetMinutes("Europe/London", new Date("2026-01-15T12:00:00Z"))).toBe(0);
  });
});

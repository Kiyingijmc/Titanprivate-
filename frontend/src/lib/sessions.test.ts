import { describe, it, expect } from "vitest";
import { sessionStates, zoneOffsetMinutes } from "./sessions";

describe("sessions", () => {
  it("london+newyork overlap active during Wed 14:00Z", () => {
    const now = new Date("2026-07-15T14:00:00Z");
    const { sessions, overlaps, activeIds, fxClosed } = sessionStates(now);
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
    expect(fxClosed).toBe(false);
  });

  it("fxClosed is true on Saturday", () => {
    const now = new Date("2026-07-18T12:00:00Z");
    const { fxClosed } = sessionStates(now);
    expect(fxClosed).toBe(true);
  });

  // 2026-08-02: the GUI drew a hard "Markets closed" banner on a Sunday while
  // SilverBullet was placing an ETHUSD limit. FX being shut is not the same as
  // the book being shut, and only the caller knows which instruments are traded.
  describe("crypto-aware closure", () => {
    const saturday = new Date("2026-07-18T12:00:00Z");

    it("a weekend with crypto in the book is fxClosed but not allClosed", () => {
      const { fxClosed, allClosed } = sessionStates(saturday, { hasCrypto: true });
      expect(fxClosed).toBe(true);
      expect(allClosed).toBe(false);
    });

    it("a weekend on an FX-only book is allClosed", () => {
      const { allClosed } = sessionStates(saturday, { hasCrypto: false });
      expect(allClosed).toBe(true);
    });

    it("defaults to FX-only when the caller says nothing", () => {
      expect(sessionStates(saturday).allClosed).toBe(true);
    });

    it("crypto does not make a weekday look closed", () => {
      const wed = new Date("2026-07-15T14:00:00Z");
      const { fxClosed, allClosed } = sessionStates(wed, { hasCrypto: true });
      expect(fxClosed).toBe(false);
      expect(allClosed).toBe(false);
    });
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

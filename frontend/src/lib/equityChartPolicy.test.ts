import { describe, it, expect } from "vitest";
import {
  drawdownSeverity,
  showsBreakerLine,
  breakerLevel,
  DD_FILL,
} from "./equityChartPolicy";

// A 1000-unit anchor with a 3% breaker gives a 30-unit daily loss budget, so
// the 1/3 and 2/3 boundaries land on exactly -10 and -20.
const ANCHOR = 1000;
const PCT = 3;

describe("drawdownSeverity (spec §6)", () => {
  it("is shallow below one third of the daily budget", () => {
    expect(drawdownSeverity(-9.99, ANCHOR, PCT)).toBe("shallow");
  });

  it("is moderate AT one third exactly", () => {
    expect(drawdownSeverity(-10, ANCHOR, PCT)).toBe("moderate");
  });

  it("is moderate AT two thirds exactly", () => {
    expect(drawdownSeverity(-20, ANCHOR, PCT)).toBe("moderate");
  });

  it("is severe past two thirds", () => {
    expect(drawdownSeverity(-20.01, ANCHOR, PCT)).toBe("severe");
  });

  it("treats drawdown sign-agnostically so a positive input cannot read as shallow", () => {
    // Drawdown is always <= 0 by construction, but a sign flip upstream must not
    // silently downgrade severity.
    expect(drawdownSeverity(25, ANCHOR, PCT)).toBe("severe");
  });

  it("falls back to moderate when the anchor is unset (0.0, the pre-anchor default)", () => {
    expect(drawdownSeverity(-25, 0, PCT)).toBe("moderate");
  });

  it("falls back to moderate when the breaker pct is unset", () => {
    expect(drawdownSeverity(-25, ANCHOR, 0)).toBe("moderate");
  });

  it("falls back to moderate for a null or non-finite drawdown", () => {
    expect(drawdownSeverity(null, ANCHOR, PCT)).toBe("moderate");
    expect(drawdownSeverity(Number.NaN, ANCHOR, PCT)).toBe("moderate");
  });

  it("maps every severity to a distinct fill", () => {
    const fills = Object.values(DD_FILL);
    expect(new Set(fills).size).toBe(fills.length);
  });
});

describe("showsBreakerLine (spec §7)", () => {
  it("shows on every intraday range", () => {
    for (const r of ["15m", "30m", "1h", "4h", "12h", "1d"] as const) {
      expect(showsBreakerLine(r), r).toBe(true);
    }
  });

  it("hides on every range spanning more than a day", () => {
    // The anchor is a TODAY-only value and no historical anchors are stored, so
    // drawing it across past days invites reading old equity against a threshold
    // that was never in force then.
    for (const r of ["1w", "1mo", "4mo", "6mo", "1y"] as const) {
      expect(showsBreakerLine(r), r).toBe(false);
    }
  });
});

describe("breakerLevel", () => {
  it("is the anchor less the breaker percentage", () => {
    expect(breakerLevel(1000, 3)).toBeCloseTo(970, 6);
  });

  it("is null when the anchor is unset, so no line is drawn at zero", () => {
    expect(breakerLevel(0, 3)).toBeNull();
  });

  it("is null when the percentage is unset", () => {
    expect(breakerLevel(1000, 0)).toBeNull();
  });
});

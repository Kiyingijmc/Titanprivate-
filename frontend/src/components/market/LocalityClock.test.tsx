import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LocalityClock } from "./LocalityClock";

describe("LocalityClock", () => {
  const fixedNow = new Date("2026-07-15T14:23:45Z");

  it("renders the current time and the resolved timezone label", () => {
    render(<LocalityClock now={fixedNow} />);
    expect(screen.getByText(/\d{1,2}:\d{2}:\d{2}/)).toBeInTheDocument();
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(screen.getByText(tz)).toBeInTheDocument();
  });

  it("renders a date string", () => {
    render(<LocalityClock now={fixedNow} />);
    expect(screen.getByTestId("locality-clock")).toBeInTheDocument();
  });

  describe("date/timezone overflow (spec §5)", () => {
    it("keeps the date and timezone as separate elements", () => {
      // Merging them into one string is what lets the date split mid-value and
      // orphan the day number onto its own line.
      render(<LocalityClock />);
      const root = screen.getByTestId("locality-clock");
      expect(root.querySelector('[data-testid="locality-date"]')).not.toBeNull();
      expect(root.querySelector('[data-testid="locality-tz"]')).not.toBeNull();
    });

    it("gives the timezone a title so truncation cannot destroy it", () => {
      // A truncated timezone with no way to read it is a smaller bug than an
      // orphaned date, but still a bug. `title` costs one attribute.
      render(<LocalityClock />);
      const tz = screen.getByTestId("locality-tz");
      expect(tz.getAttribute("title")).toBe(tz.textContent);
      expect(tz.textContent!.length).toBeGreaterThan(0);   // or the assertion is vacuous
    });
  });
});

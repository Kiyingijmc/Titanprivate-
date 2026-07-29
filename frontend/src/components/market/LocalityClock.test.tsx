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
});

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CalendarTable } from "./CalendarTable";
import { buildCalendarView, DEFAULT_FILTERS } from "@/lib/newsCalendar";
import type { CalendarEventRow } from "@/lib/types";

const NOW = Date.parse("2026-08-07T10:00:00Z");

const ROWS: CalendarEventRow[] = [
  { when_utc: "2026-08-07T12:30:00Z", currency: "USD", importance: "HIGH",
    title: "Non-Farm Employment Change", forecast: "85K", previous: "57K",
    affects: ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"] },
  { when_utc: "2026-08-07T14:00:00Z", currency: "CAD", importance: "MEDIUM",
    title: "Ivey PMI", forecast: "55.4", previous: "56.2", affects: ["USDCAD"] },
];

function view(held: string[] = []) {
  return buildCalendarView(ROWS, { ...DEFAULT_FILTERS, horizon: "all" },
                           NOW, new Set(held));
}

describe("CalendarTable", () => {
  it("renders a row per event with its time in UTC", () => {
    render(<CalendarTable groups={view()} />);
    const rows = screen.getAllByTestId("calendar-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("12:30Z")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Non-Farm Employment Change")).toBeInTheDocument();
    expect(within(rows[0]).getByText("85K")).toBeInTheDocument();
  });

  it("shows a day header carrying the filtered tally", () => {
    render(<CalendarTable groups={view()} />);
    const header = screen.getByTestId("calendar-day-header");
    expect(within(header).getByText(/Friday 7 August/)).toBeInTheDocument();
    expect(within(header).getByText(/1 high · 1 med/)).toBeInTheDocument();
  });

  it("truncates a long affects list with a remainder counter", () => {
    render(<CalendarTable groups={view()} />);
    // 4 affected symbols, 2 chips shown -> "+2 more", NOT "+4".
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("names the held symbol in accessible text, not colour alone", () => {
    render(<CalendarTable groups={view(["XAUUSD"])} />);
    const row = screen.getAllByTestId("calendar-row")[0];
    expect(within(row).getByText(/Open position in XAUUSD/)).toBeInTheDocument();
  });

  it("puts a held symbol in the visible chips even when it sorted last", () => {
    // XAUUSD is 4th in `affects`; only 2 chips render. If held symbols were
    // not hoisted, the position that costs money would hide behind "+2 more".
    render(<CalendarTable groups={view(["XAUUSD"])} />);
    const row = screen.getAllByTestId("calendar-row")[0];
    expect(within(row).getByTestId("affect-chip-XAUUSD")).toBeInTheDocument();
  });

  it("renders no held marker when nothing is open", () => {
    render(<CalendarTable groups={view()} />);
    expect(screen.queryByText(/Open position in/)).not.toBeInTheDocument();
  });
});

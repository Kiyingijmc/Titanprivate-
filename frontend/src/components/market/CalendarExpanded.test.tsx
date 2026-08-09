import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CalendarExpanded } from "./CalendarExpanded";
import type { NewsCalendar, Position } from "@/lib/types";

const soon = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();

const OK: NewsCalendar = {
  status: "ok", cache_age_min: 12, horizon_truncated: false,
  events: [
    { when_utc: soon(2), currency: "USD", importance: "HIGH",
      title: "Non-Farm Employment Change", forecast: "85K", previous: "57K",
      affects: ["EURUSD", "XAUUSD"] },
    { when_utc: soon(3), currency: "CHF", importance: "LOW",
      title: "SECO Consumer Climate", affects: [] },
  ],
};

const POSITIONS = [{ symbol: "XAUUSD" }] as unknown as Position[];
const apiFor = (payload: NewsCalendar) => ({ getNewsCalendar: vi.fn().mockResolvedValue(payload) });

describe("CalendarExpanded", () => {
  it("renders rows once the calendar loads", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={POSITIONS} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    expect(screen.getByText("Non-Farm Employment Change")).toBeInTheDocument();
  });

  it("distinguishes a filtered-to-zero result from an unavailable feed", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    // Turn every impact off -> zero rows, but the feed is healthy.
    await userEvent.click(screen.getByRole("button", { name: "High" }));
    await userEvent.click(screen.getByRole("button", { name: "Med" }));
    expect(screen.getByTestId("calendar-no-match")).toBeInTheDocument();
    expect(screen.queryByTestId("calendar-unavailable")).not.toBeInTheDocument();
  });

  it("restores every row via Reset filters", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    await userEvent.click(screen.getByRole("button", { name: "High" }));
    await userEvent.click(screen.getByRole("button", { name: "Med" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0);
  });

  it("shows the unavailable state when the backend degrades", async () => {
    const payload: NewsCalendar = { status: "unavailable", events: [] };
    render(<CalendarExpanded open api={apiFor(payload)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-unavailable")).toBeInTheDocument());
    expect(screen.queryByTestId("calendar-no-match")).not.toBeInTheDocument();
  });

  it("warns when the horizon is truncated", async () => {
    const payload: NewsCalendar = { ...OK, horizon_truncated: true };
    render(<CalendarExpanded open api={apiFor(payload)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-truncated")).toBeInTheDocument());
    expect(screen.getByText(/Next week's calendar is unavailable/)).toBeInTheDocument();
  });

  it("shows no truncation warning when the horizon is whole", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("calendar-truncated")).not.toBeInTheDocument();
  });

  it("does not fetch while closed", async () => {
    const api = apiFor(OK);
    render(<CalendarExpanded open={false} api={api} positions={[]} />);
    await new Promise(r => setTimeout(r, 20));
    expect(api.getNewsCalendar).not.toHaveBeenCalled();
  });
});

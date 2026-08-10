import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CalendarExpanded } from "./CalendarExpanded";
import { dayFormatter } from "./CalendarTable";
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

  // The three outcomes that can put a near-empty body on screen must be
  // mutually distinguishable — a healthy feed with nothing scheduled must
  // not read as "you filtered something out" (calendar-no-match) or as a
  // dead feed (calendar-unavailable). Asserted in all three directions: a
  // one-sided assertion would pass even if two states rendered together.
  it("shows a genuinely quiet week distinctly from filtered-to-zero and a dead feed", async () => {
    const payload: NewsCalendar = { status: "ok", horizon_truncated: false, events: [] };
    render(<CalendarExpanded open api={apiFor(payload)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-empty-window")).toBeInTheDocument());
    expect(screen.queryByTestId("calendar-no-match")).not.toBeInTheDocument();
    expect(screen.queryByTestId("calendar-unavailable")).not.toBeInTheDocument();
    // Nothing to reset — offering the control would be the same misleading
    // implication this state exists to avoid.
    expect(screen.queryByRole("button", { name: "Reset filters" })).not.toBeInTheDocument();
  });

  it("warns when the horizon is truncated, naming the date it stops at", async () => {
    const payload: NewsCalendar = { ...OK, horizon_truncated: true };
    const latestMs = Math.max(...payload.events.map(e => Date.parse(e.when_utc)));
    const expectedDate = dayFormatter.format(new Date(latestMs));
    render(<CalendarExpanded open api={apiFor(payload)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-truncated")).toBeInTheDocument());
    expect(screen.getByText(`Next week's calendar is unavailable — showing through ${expectedDate}.`)).toBeInTheDocument();
  });

  it("warns about truncation without a date when no events exist to derive one from", async () => {
    const payload: NewsCalendar = { status: "ok", horizon_truncated: true, events: [] };
    render(<CalendarExpanded open api={apiFor(payload)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-truncated")).toBeInTheDocument());
    expect(screen.getByText("Next week's calendar is unavailable.")).toBeInTheDocument();
    expect(screen.queryByText(/showing through/)).not.toBeInTheDocument();
  });

  it("shows no truncation warning when the horizon is whole", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("calendar-truncated")).not.toBeInTheDocument();
  });

  it("shows the stale banner for a stale payload and not for an ok one", async () => {
    const stale: NewsCalendar = { ...OK, status: "stale", cache_age_min: 90 };
    const first = render(<CalendarExpanded open api={apiFor(stale)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-stale")).toBeInTheDocument());
    first.unmount();

    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("calendar-stale")).not.toBeInTheDocument();
  });

  it("does not fetch while closed", async () => {
    const api = apiFor(OK);
    render(<CalendarExpanded open={false} api={api} positions={[]} />);
    await new Promise(r => setTimeout(r, 20));
    expect(api.getNewsCalendar).not.toHaveBeenCalled();
  });
});

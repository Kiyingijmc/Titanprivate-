import { describe, expect, it } from "vitest";
import { buildCalendarView, horizonEndMs, DEFAULT_FILTERS,
         type CalendarFilterState } from "./newsCalendar";
import type { CalendarEventRow } from "./types";

const NOW = Date.parse("2026-08-07T10:00:00Z");
const DAY = 86_400_000;

function ev(when: string, importance: CalendarEventRow["importance"],
            title: string, currency = "USD", affects: string[] = ["XAUUSD", "EURUSD"]):
            CalendarEventRow {
  return { when_utc: when, currency, importance, title, affects,
           forecast: "1.0", previous: "0.9" };
}

const ALL: CalendarFilterState = { impacts: ["HIGH", "MEDIUM", "LOW"],
                                   affectsMyBookOnly: false, horizon: "all" };

describe("horizonEndMs", () => {
  it("ends 'today' at the last instant of the current UTC day", () => {
    expect(horizonEndMs(NOW, "today")).toBe(Date.parse("2026-08-07T23:59:59.999Z"));
  });
  it("counts 3d and 7d forward from now", () => {
    expect(horizonEndMs(NOW, "3d")).toBe(NOW + 3 * DAY);
    expect(horizonEndMs(NOW, "7d")).toBe(NOW + 7 * DAY);
  });
  it("makes 'all' unbounded", () => {
    expect(horizonEndMs(NOW, "all")).toBe(Infinity);
  });
});

describe("buildCalendarView — filtering", () => {
  it("keeps only the selected impact levels", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "H"),
                  ev("2026-08-07T13:00:00Z", "MEDIUM", "M"),
                  ev("2026-08-07T14:00:00Z", "LOW", "L")];
    const out = buildCalendarView(rows, { ...ALL, impacts: ["HIGH", "MEDIUM"] }, NOW, new Set());
    const titles = out.flatMap(g => g.rows.map(r => r.title));
    expect(titles.length).toBeGreaterThan(0);
    expect(titles).toEqual(["H", "M"]);
  });

  it("drops events whose currency reaches none of the traded symbols", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "USD one", "USD", ["XAUUSD"]),
                  ev("2026-08-07T13:00:00Z", "HIGH", "CHF one", "CHF", [])];
    const out = buildCalendarView(rows, { ...ALL, affectsMyBookOnly: true }, NOW, new Set());
    const titles = out.flatMap(g => g.rows.map(r => r.title));
    expect(titles.length).toBeGreaterThan(0);
    expect(titles).toEqual(["USD one"]);
  });

  it("includes an event landing exactly on the horizon boundary", () => {
    const rows = [ev(new Date(NOW + 3 * DAY).toISOString(), "HIGH", "boundary")];
    const out = buildCalendarView(rows, { ...ALL, horizon: "3d" }, NOW, new Set());
    expect(out.flatMap(g => g.rows.map(r => r.title))).toEqual(["boundary"]);
  });

  it("excludes an event one millisecond past the horizon", () => {
    const rows = [ev(new Date(NOW + 3 * DAY + 1).toISOString(), "HIGH", "past-edge")];
    const out = buildCalendarView(rows, { ...ALL, horizon: "3d" }, NOW, new Set());
    expect(out).toEqual([]);
  });
});

describe("buildCalendarView — grouping", () => {
  it("splits events across the UTC midnight seam", () => {
    const rows = [ev("2026-08-07T23:59:00Z", "HIGH", "late"),
                  ev("2026-08-08T00:01:00Z", "HIGH", "early")];
    const out = buildCalendarView(rows, ALL, NOW, new Set());
    expect(out.map(g => g.dayIso)).toEqual(["2026-08-07", "2026-08-08"]);
    expect(out[0].rows.map(r => r.title)).toEqual(["late"]);
    expect(out[1].rows.map(r => r.title)).toEqual(["early"]);
  });

  it("tallies the FILTERED rows, so the header cannot contradict the body", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "H1"),
                  ev("2026-08-07T13:00:00Z", "HIGH", "H2"),
                  ev("2026-08-07T14:00:00Z", "LOW", "L1")];
    const out = buildCalendarView(rows, { ...ALL, impacts: ["HIGH"] }, NOW, new Set());
    expect(out).toHaveLength(1);
    expect(out[0].tally).toEqual({ HIGH: 2, MEDIUM: 0, LOW: 0 });
    expect(out[0].rows).toHaveLength(2);
  });
});

describe("buildCalendarView — ordering and held symbols", () => {
  it("orders simultaneous events deterministically regardless of input order", () => {
    // The real NFP case: five releases share 12:30Z. Under a 60s poll an
    // unstable comparator would reshuffle these rows on every refresh.
    const a = ev("2026-08-07T12:30:00Z", "HIGH", "Average Hourly Earnings m/m");
    const b = ev("2026-08-07T12:30:00Z", "HIGH", "Non-Farm Employment Change");
    const c = ev("2026-08-07T12:30:00Z", "HIGH", "Unemployment Rate", "CAD", []);
    const first = buildCalendarView([a, b, c], ALL, NOW, new Set());
    const second = buildCalendarView([c, b, a], ALL, NOW, new Set());
    expect(first[0].rows.map(r => r.title)).toEqual(second[0].rows.map(r => r.title));
    expect(first[0].rows).toHaveLength(3);
  });

  it("sorts held symbols to the front of orderedAffects", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "NFP", "USD",
                     ["EURUSD", "GBPUSD", "XAUUSD"])];
    const out = buildCalendarView(rows, ALL, NOW, new Set(["XAUUSD"]));
    expect(out[0].rows[0].orderedAffects[0]).toBe("XAUUSD");
    expect(out[0].rows[0].heldAffects).toEqual(["XAUUSD"]);
    expect(out[0].rows[0].isHeld).toBe(true);
  });

  it("marks a row unheld when no affected symbol is open", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "NFP", "USD", ["EURUSD"])];
    const out = buildCalendarView(rows, ALL, NOW, new Set(["XAUUSD"]));
    expect(out[0].rows[0].isHeld).toBe(false);
    expect(out[0].rows[0].heldAffects).toEqual([]);
  });
});

describe("DEFAULT_FILTERS", () => {
  it("hides LOW, spans 7d, and does not pre-narrow to the book", () => {
    expect(DEFAULT_FILTERS.impacts).toEqual(["HIGH", "MEDIUM"]);
    expect(DEFAULT_FILTERS.horizon).toBe("7d");
    expect(DEFAULT_FILTERS.affectsMyBookOnly).toBe(false);
  });
});

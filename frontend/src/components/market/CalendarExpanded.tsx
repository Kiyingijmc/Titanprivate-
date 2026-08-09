import { useMemo, useState } from "react";
import { CalendarFilters } from "./CalendarFilters";
import { CalendarTable } from "./CalendarTable";
import { buildCalendarView, DEFAULT_FILTERS, type CalendarFilterState }
  from "@/lib/newsCalendar";
import { useNewsCalendar } from "@/lib/useNewsCalendar";
import type { Api } from "@/lib/api";
import type { Position } from "@/lib/types";

function EmptyState({ testId, title, hint, action }:
    { testId: string; title: string; hint: string; action?: React.ReactNode }) {
  return (
    <div data-testid={testId}
         className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
      <span className="text-sm text-muted-foreground">{title}</span>
      <span className="text-xs text-muted-foreground/70">{hint}</span>
      {action}
    </div>
  );
}

/**
 * The maximized Economic Calendar body (spec §4).
 *
 * Two of the states here exist purely because they would otherwise be
 * indistinguishable from good news: a truncated horizon and a filter that
 * matched nothing both render an almost-empty table, and "nothing is
 * scheduled" is the one conclusion an economic calendar must never invite by
 * accident.
 */
export function CalendarExpanded({ open, api, positions }: {
  open: boolean;
  api: Pick<Api, "getNewsCalendar">;
  positions?: Position[];
}) {
  const [filters, setFilters] = useState<CalendarFilterState>(DEFAULT_FILTERS);
  const { data, loading } = useNewsCalendar(api, open);

  const held = useMemo(
    () => new Set((positions ?? []).map(p => p.symbol)),
    [positions]);

  const groups = useMemo(
    () => buildCalendarView(data?.events ?? [], filters, Date.now(), held),
    [data, filters, held]);

  const unavailable = !data || data.status === "unavailable";
  const rowCount = groups.reduce((n, g) => n + g.rows.length, 0);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <CalendarFilters value={filters} onChange={setFilters} />

      {data?.status === "stale" && (
        <div data-testid="calendar-stale"
             className="border-b border-warning/40 bg-warning/10 px-4 py-1.5 text-xs text-warning">
          Calendar data is stale
          {data.cache_age_min != null ? ` (${data.cache_age_min}m old)` : ""}.
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && !data ? (
          <EmptyState testId="calendar-loading" title="Loading calendar…"
                      hint="Fetching upcoming releases." />
        ) : unavailable ? (
          <EmptyState
            testId="calendar-unavailable"
            title="Economic calendar unavailable"
            hint="No news feed is connected yet — populated once the calendar source is live." />
        ) : rowCount === 0 ? (
          <EmptyState
            testId="calendar-no-match"
            title="No events match these filters"
            hint="The feed is healthy — widen the impact levels or the date range."
            action={
              <button
                type="button"
                onClick={() => setFilters(DEFAULT_FILTERS)}
                className="mt-1 rounded-full border border-accent bg-accent/20 px-3 py-0.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Reset filters
              </button>
            } />
        ) : (
          <CalendarTable groups={groups} />
        )}
      </div>

      {data?.horizon_truncated && (
        <div data-testid="calendar-truncated"
             className="border-t border-border bg-surface-1 px-4 py-2 text-xs text-warning">
          Next week's calendar is unavailable — showing only what this week's feed carries.
        </div>
      )}
    </div>
  );
}

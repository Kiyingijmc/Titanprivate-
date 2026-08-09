import { ImpactChip } from "./ImpactChip";
import type { DayGroup, DecoratedRow } from "@/lib/newsCalendar";
import { cn } from "@/lib/utils";

const MAX_CHIPS = 2;

// Exported so CalendarExpanded's truncation banner can name the horizon's
// last known date with the SAME format as the day headers below it — one
// date format for the whole feature, not two that could drift apart.
export const dayFormatter = new Intl.DateTimeFormat("en-GB", {
  weekday: "long", day: "numeric", month: "long", timeZone: "UTC",
});
const timeFormatter = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
});

/** UTC everywhere, matching the collapsed card (NewsPanel.tsx:136-142), so the
 *  two surfaces can never disagree about when an event is. */
function formatTime(whenUtc: string): string {
  const at = new Date(whenUtc);
  return Number.isNaN(at.getTime()) ? "--:--" : `${timeFormatter.format(at)}Z`;
}

function formatDay(dayIso: string): string {
  const at = new Date(`${dayIso}T00:00:00Z`);
  return Number.isNaN(at.getTime()) ? dayIso : dayFormatter.format(at);
}

function tallyText(tally: DayGroup["tally"]): string {
  const parts: string[] = [];
  if (tally.HIGH) parts.push(`${tally.HIGH} high`);
  if (tally.MEDIUM) parts.push(`${tally.MEDIUM} med`);
  if (tally.LOW) parts.push(`${tally.LOW} low`);
  return parts.join(" · ");
}

function Affects({ row }: { row: DecoratedRow }) {
  const shown = row.orderedAffects.slice(0, MAX_CHIPS);
  const rest = row.orderedAffects.length - shown.length;
  const held = new Set(row.heldAffects);
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1"
         title={row.orderedAffects.join(", ")}>
      {shown.map(symbol => (
        <span
          key={symbol}
          data-testid={`affect-chip-${symbol}`}
          className={cn(
            "inline-flex items-center gap-1 rounded-full border px-1.5 py-px font-mono text-[10px]",
            held.has(symbol)
              ? "border-accent bg-accent/20 text-foreground"
              : "border-border bg-surface-2 text-muted-foreground")}
        >
          {held.has(symbol) && <span className="size-1 rounded-full bg-accent" aria-hidden />}
          {symbol}
        </span>
      ))}
      {rest > 0 && <span className="text-[10px] text-muted-foreground">+{rest} more</span>}
    </div>
  );
}

export function CalendarTable({ groups }: { groups: DayGroup[] }) {
  return (
    <table className="w-full table-fixed border-collapse text-xs">
      <caption className="sr-only">
        Upcoming economic releases, grouped by UTC day
      </caption>
      <thead>
        <tr className="sticky top-0 z-10 bg-surface-1">
          <th scope="col" className="w-[68px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Time</th>
          <th scope="col" className="w-[76px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Impact</th>
          <th scope="col" className="w-[52px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Cur</th>
          <th scope="col" className="px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Event</th>
          <th scope="col" className="w-[80px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Forecast</th>
          <th scope="col" className="w-[80px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Previous</th>
          <th scope="col" className="w-[176px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Affects</th>
        </tr>
      </thead>
      {groups.map(group => (
        <tbody key={group.dayIso}>
          <tr>
            <th
              scope="colgroup"
              colSpan={7}
              data-testid="calendar-day-header"
              className="sticky top-[26px] z-[9] border-y border-border bg-surface-2 px-4 py-1 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
            >
              <span className="flex items-center justify-between gap-2">
                <span>{formatDay(group.dayIso)}</span>
                <span className="font-normal normal-case tracking-normal">
                  {tallyText(group.tally)}
                </span>
              </span>
            </th>
          </tr>
          {group.rows.map(row => (
            <tr
              key={`${row.when_utc}-${row.currency}-${row.title}`}
              data-testid="calendar-row"
              className={cn("border-b border-border/60", row.isHeld && "bg-accent/[0.07]")}
            >
              <td className="px-2 py-1.5 font-mono tabnum text-muted-foreground">{formatTime(row.when_utc)}</td>
              <td className="px-2 py-1.5"><ImpactChip impact={row.importance} /></td>
              <td className="px-2 py-1.5 font-mono text-muted-foreground">{row.currency}</td>
              <td className="min-w-0 px-2 py-1.5">
                <span className="block truncate text-foreground" title={row.title}>
                  {row.url ? (
                    <a href={row.url} target="_blank" rel="noopener noreferrer"
                       className="underline-offset-2 hover:underline">{row.title}</a>
                  ) : row.title}
                </span>
                {row.isHeld && (
                  // The third channel. Tint + outlined chip are both colour;
                  // this is the one a colour-blind operator can still read.
                  <span className="sr-only">
                    Open position in {row.heldAffects.join(", ")}
                  </span>
                )}
              </td>
              <td className="px-2 py-1.5 font-mono tabnum text-muted-foreground">{row.forecast ?? "—"}</td>
              <td className="px-2 py-1.5 font-mono tabnum text-muted-foreground">{row.previous ?? "—"}</td>
              <td className="px-2 py-1.5"><Affects row={row} /></td>
            </tr>
          ))}
        </tbody>
      ))}
    </table>
  );
}

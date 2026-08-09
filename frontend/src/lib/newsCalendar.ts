import type { CalendarEventRow } from "./types";

export type Impact = "HIGH" | "MEDIUM" | "LOW";
export type Horizon = "today" | "3d" | "7d" | "all";

export const IMPACT_ORDER: Impact[] = ["HIGH", "MEDIUM", "LOW"];
export const HORIZONS: { id: Horizon; label: string }[] = [
  { id: "today", label: "Today" }, { id: "3d", label: "3d" },
  { id: "7d", label: "7d" }, { id: "all", label: "All" },
];

export interface CalendarFilterState {
  impacts: Impact[];
  affectsMyBookOnly: boolean;
  horizon: Horizon;
}

/** LOW is 76% of the feed, so it is off by default. `affectsMyBookOnly` is
 *  OFF: narrowing is one click, but a filter that silently hides 14% of the
 *  calendar before the operator touches anything gets blamed after a surprise. */
export const DEFAULT_FILTERS: CalendarFilterState = {
  impacts: ["HIGH", "MEDIUM"],
  affectsMyBookOnly: false,
  horizon: "7d",
};

export interface DecoratedRow extends CalendarEventRow {
  /** Affected symbols with an open position — always a prefix of orderedAffects. */
  heldAffects: string[];
  /** `affects` with held symbols first, so truncation never hides an open one. */
  orderedAffects: string[];
  isHeld: boolean;
}

export interface DayGroup {
  dayIso: string;                    // "2026-08-07"
  rows: DecoratedRow[];
  tally: Record<Impact, number>;
}

const DAY_MS = 86_400_000;

export function horizonEndMs(nowMs: number, horizon: Horizon): number {
  if (horizon === "all") return Infinity;
  if (horizon === "today") {
    // The rest of the current UTC day, not now+24h — "Today" is a calendar
    // day, and the whole surface is UTC (spec §4.2).
    const d = new Date(nowMs);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(),
                    23, 59, 59, 999);
  }
  return nowMs + (horizon === "3d" ? 3 : 7) * DAY_MS;
}

/** The UTC day, taken from the ISO STRING rather than a Date.
 *  `new Date(x).getDate()` would resolve in the viewer's local timezone and
 *  would move events across day boundaries west of UTC. */
function utcDayOf(whenUtc: string): string {
  return whenUtc.slice(0, 10);
}

function decorate(event: CalendarEventRow, held: Set<string>): DecoratedRow {
  const affects = event.affects ?? [];
  const heldAffects = affects.filter(s => held.has(s));
  const rest = affects.filter(s => !held.has(s));
  return { ...event, heldAffects, orderedAffects: [...heldAffects, ...rest],
           isHeld: heldAffects.length > 0 };
}

export function buildCalendarView(
  events: CalendarEventRow[],
  filters: CalendarFilterState,
  nowMs: number,
  heldSymbols: Set<string>,
): DayGroup[] {
  const impacts = new Set(filters.impacts);
  const end = horizonEndMs(nowMs, filters.horizon);

  const kept = (events ?? []).filter(e => {
    if (!impacts.has(e.importance)) return false;
    if (filters.affectsMyBookOnly && (e.affects ?? []).length === 0) return false;
    const at = Date.parse(e.when_utc);
    if (!Number.isFinite(at)) return false;      // a malformed stamp is not a row
    return at <= end;
  });

  // Explicit tiebreak on (time, currency, title). The backend sorts by time
  // alone, and CalendarStore.events() sorts a dict's values — so two events
  // sharing a timestamp have no stable relative order upstream. Five releases
  // really do share 12:30Z on an NFP day; without this they reshuffle on
  // every 60s poll.
  kept.sort((a, b) =>
    Date.parse(a.when_utc) - Date.parse(b.when_utc) ||
    a.currency.localeCompare(b.currency) ||
    a.title.localeCompare(b.title));

  const groups = new Map<string, DayGroup>();
  for (const event of kept) {
    const dayIso = utcDayOf(event.when_utc);
    let group = groups.get(dayIso);
    if (!group) {
      group = { dayIso, rows: [], tally: { HIGH: 0, MEDIUM: 0, LOW: 0 } };
      groups.set(dayIso, group);
    }
    group.rows.push(decorate(event, heldSymbols));
    group.tally[event.importance] += 1;          // tallies the FILTERED set
  }
  return [...groups.values()];
}

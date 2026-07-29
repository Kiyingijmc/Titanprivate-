// Pure market-session engine: open/overlap/countdown, DST-correct.
// No React/DOM. Deterministic given an injected nowUtc — never calls Date.now()
// or `new Date()` with no arguments internally.

export interface MarketSession {
  id: "sydney" | "tokyo" | "london" | "newyork";
  label: string;
  zone: string;
  openLocalH: number;
  closeLocalH: number;
}

export const SESSIONS: MarketSession[] = [
  { id: "sydney", label: "Sydney", zone: "Australia/Sydney", openLocalH: 7, closeLocalH: 16 },
  { id: "tokyo", label: "Tokyo", zone: "Asia/Tokyo", openLocalH: 9, closeLocalH: 18 },
  { id: "london", label: "London", zone: "Europe/London", openLocalH: 8, closeLocalH: 17 },
  { id: "newyork", label: "New York", zone: "America/New_York", openLocalH: 8, closeLocalH: 17 },
];

/**
 * UTC offset (in minutes) for an IANA zone at a given instant.
 * Uses the formatToParts epoch trick: format `at` in the target zone into
 * Y/M/D/H/M/S parts, rebuild a UTC timestamp from those parts, and diff from
 * `at.getTime()`. DST-correct because Intl applies the zone's rules for that
 * specific instant.
 */
export function zoneOffsetMinutes(zone: string, at: Date): number {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const parts = dtf.formatToParts(at);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  const year = get("year");
  const month = get("month");
  const day = get("day");
  const hour = get("hour");
  const minute = get("minute");
  const second = get("second");
  const asUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  return Math.round((asUtc - at.getTime()) / 60000);
}

export interface SessionState {
  id: string;
  label: string;
  open: boolean;
  localTime: string;
  statusLabel: string;
  countdownMin: number;
  startUtcMin: number;
  endUtcMin: number;
}

function mod(n: number, m: number): number {
  return ((n % m) + m) % m;
}

function inWindow(nowMin: number, start: number, end: number): boolean {
  if (start < end) {
    return nowMin >= start && nowMin < end;
  }
  // wraps past midnight UTC
  return nowMin >= start || nowMin < end;
}

function fmtCountdown(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function localTimeString(zone: string, at: Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(at);
}

export function sessionStates(nowUtc: Date): {
  sessions: SessionState[];
  overlaps: Array<{ ids: [string, string]; active: boolean }>;
  activeIds: string[];
  weekendClosed: boolean;
} {
  const nowMin = nowUtc.getUTCHours() * 60 + nowUtc.getUTCMinutes();

  const sessions: SessionState[] = SESSIONS.map((session) => {
    const offset = zoneOffsetMinutes(session.zone, nowUtc);
    const startUtcMin = mod(session.openLocalH * 60 - offset, 1440);
    const endUtcMin = mod(session.closeLocalH * 60 - offset, 1440);
    const open = inWindow(nowMin, startUtcMin, endUtcMin);
    const countdownMin = mod((open ? endUtcMin : startUtcMin) - nowMin, 1440);
    const statusLabel = open
      ? `Open · closes in ${fmtCountdown(countdownMin)}`
      : `Opens in ${fmtCountdown(countdownMin)}`;

    return {
      id: session.id,
      label: session.label,
      open,
      localTime: localTimeString(session.zone, nowUtc),
      statusLabel,
      countdownMin,
      startUtcMin,
      endUtcMin,
    };
  });

  const byId = new Map(sessions.map((s) => [s.id, s]));
  const overlapPairs: Array<[string, string]> = [
    ["london", "newyork"],
    ["tokyo", "london"],
    ["sydney", "tokyo"],
  ];
  const overlaps = overlapPairs.map(([a, b]) => ({
    ids: [a, b] as [string, string],
    active: Boolean(byId.get(a)?.open && byId.get(b)?.open),
  }));

  const activeIds = sessions.filter((s) => s.open).map((s) => s.id);

  const day = nowUtc.getUTCDay();
  const hour = nowUtc.getUTCHours();
  const weekendClosed =
    day === 6 || (day === 0 && hour < 22) || (day === 5 && hour >= 22);

  return { sessions, overlaps, activeIds, weekendClosed };
}

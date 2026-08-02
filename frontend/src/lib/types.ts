export interface Health { bridge_connected: boolean; last_heartbeat_age_s: number; paused: boolean; last_error: string | null; }
export interface Account { balance: number; equity: number; }
export interface Position {
  ticket: number; symbol: string; side: "BUY" | "SELL"; lots: number;
  entry: number; sl: number; tp: number; pnl: number; grade: string; strategy: string;
}
export interface ArbiterBlock {
  stats: { submitted: number; approved: number; blocked_by: Record<string, number> };
  throttle: { enabled: boolean; current_mult: number };
}
export interface RegistryRow {
  id: string; version: string; status: string; state: string; tf?: string; priority?: number; family?: string;
}
export interface DollarBias {
  source: "index" | "computed" | "unavailable";
  value: number | null;
  bias: number;
  trend: number[];
  contributors: { symbol: string; contribution: number }[];
}
export interface Snapshot {
  health: Health; account: Account; positions: Position[]; arbiter: ArbiterBlock; registry: RegistryRow[];
  dollar?: DollarBias;
}
export interface FeedEvent { topic: string; ts: number; [k: string]: unknown; }
export interface SettingRow { key: string; value: unknown; source: "default" | "override"; tier: "live" | "restart"; }
export interface HistoryRow { [k: string]: unknown; }
export interface CommandResult { status: string; result?: unknown; detail?: string; command?: string; }
export interface SettingsPatchResult { applied?: string; restart_required?: boolean; value?: unknown; detail?: string; }

export const RANGE_NAMES = ["15m","30m","1h","4h","12h","1d","1w","1mo","4mo","6mo","1y"] as const;
export type RangeName = (typeof RANGE_NAMES)[number];

/**
 * One downsampled bucket. A `null` entry in EquitySeries.points is a data gap.
 *
 * Only `ts` and `equity` are load-bearing. Everything else is OPTIONAL on
 * purpose: the backend builds a point as one tuple entry per registered series,
 * so dropping a series from the registry is exactly as easy as adding one, and
 * would silently omit the key. Declaring `balance`/`peak` as required `number`
 * alongside an index signature made that unrepresentable to `tsc` while still
 * happening at runtime — `undefined` then flowed through `!== null` filters into
 * `Math.min(...)`, whose `NaN` renders a blank chart with no error and no empty
 * state. Consumers MUST runtime-guard with `Number.isFinite` before arithmetic.
 */
export interface EquityPoint {
  ts: number;                 // UTC epoch seconds (SERVER clock)
  equity: number;
  balance?: number;
  peak?: number;
  [series: string]: number | undefined;   // future registry series arrive here
}

export interface EquityCoverage {
  first_sample_ts: number | null;
  n: number;
  series_first_ts: Record<string, number | null>;
  gaps: [number, number][];
}

export interface EquitySeries {
  range: string;
  tier: "fine" | "coarse";
  bucket_s: number | null;
  series: string[];
  points: (EquityPoint | null)[];
  coverage: EquityCoverage;
}

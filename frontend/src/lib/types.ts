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

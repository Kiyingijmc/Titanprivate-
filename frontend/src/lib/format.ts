export function money(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function signedPnl(n: number): { text: string; tone: "profit" | "loss" | "flat" } {
  const tone = n > 0 ? "profit" : n < 0 ? "loss" : "flat";
  const sign = n > 0 ? "+" : "";                         // negatives already carry "-"
  return { text: `${sign}${money(n)}`, tone };
}

/**
 * Instrument price: trims float noise and kills scientific notation (e.g. 1e-5)
 * while preserving up to broker-scale precision. No fixed decimals — instruments
 * vary (JPY 3, FX 5, indices 1) and the client has no per-symbol digit count.
 */
export function price(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 5 });
}

/** Lot size to a stable 2 decimals so the column doesn't jitter. */
export function lots(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** The single P&L tone→text-color mapping shared by tiles, tables and the status bar. */
export function pnlToneClass(tone: "profit" | "loss" | "flat"): string {
  return tone === "profit" ? "text-profit" : tone === "loss" ? "text-loss" : "text-muted-foreground";
}

export function ageLabel(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

export function sideLabel(side: "BUY" | "SELL"): "BUY" | "SELL" { return side; }

export function money(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function signedPnl(n: number): { text: string; tone: "profit" | "loss" | "flat" } {
  const tone = n > 0 ? "profit" : n < 0 ? "loss" : "flat";
  const sign = n > 0 ? "+" : "";                         // negatives already carry "-"
  return { text: `${sign}${money(n)}`, tone };
}

export function ageLabel(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

export function sideLabel(side: "BUY" | "SELL"): "BUY" | "SELL" { return side; }

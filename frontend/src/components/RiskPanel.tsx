import { ShieldAlert, ShieldCheck, AlertOctagon } from "lucide-react";
import type { RiskBlock } from "@/lib/types";
import { money } from "@/lib/format";
import { cn } from "@/lib/utils";

function Meter({ pct, danger }: { pct: number; danger: boolean }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div
        className={cn("h-full rounded-full", danger ? "bg-loss" : "bg-accent")}
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        aria-hidden
      />
    </div>
  );
}

function Row({
  label,
  value,
  detail,
  children,
}: {
  label: string;
  value: string;
  detail?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
        <span className="font-mono tabnum text-sm">{value}</span>
      </div>
      {children}
      {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
    </div>
  );
}

/**
 * The two guards that can stop trading outright, neither of which had any GUI
 * surface before 2026-08-02:
 *
 *  - the RISK-01 daily drawdown breaker, anchored to a persisted day-start
 *    equity that survives restarts;
 *  - the book-wide exposure cap, which refuses EVERY symbol when a single row's
 *    risk is un-computable.
 *
 * The un-computable case is the one this panel exists for. Without it a total
 * trading halt is indistinguishable from a quiet market.
 */
export function RiskPanel({ risk }: { risk: RiskBlock }) {
  const blocked = risk.book_risk === null;
  const ddUsedPct =
    risk.day_pnl_pct !== null && risk.max_daily_dd_pct > 0
      ? (Math.max(0, -risk.day_pnl_pct) / risk.max_daily_dd_pct) * 100
      : 0;
  const bookUsedPct =
    risk.book_risk_pct !== null && risk.max_book_risk_pct > 0
      ? (risk.book_risk_pct / risk.max_book_risk_pct) * 100
      : 0;

  return (
    <div className="flex flex-col gap-4">
      <div
        data-testid="risk-breaker-state"
        data-state={blocked ? "blocked" : risk.can_trade ? "ok" : "tripped"}
        className={cn(
          "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
          blocked || !risk.can_trade
            ? "border-loss/40 bg-loss/10 text-loss"
            : "border-border bg-surface-2 text-muted-foreground"
        )}
      >
        {blocked ? (
          <AlertOctagon className="mt-0.5 size-4 shrink-0" aria-hidden />
        ) : risk.can_trade ? (
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        ) : (
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        )}
        <span>
          {blocked ? (
            <>
              <strong>All trading blocked</strong> — book risk is un-computable
              {risk.blocker && (
                <>
                  {" "}
                  because of {risk.blocker.source} {risk.blocker.symbol} (ticket{" "}
                  <span className="font-mono tabnum">{risk.blocker.ticket}</span>). Every symbol
                  stays blocked until that row has a stop Titan can price.
                </>
              )}
            </>
          ) : !risk.can_trade ? (
            <>
              <strong>Daily drawdown breaker tripped</strong> — no new entries until the next
              trading day.
            </>
          ) : (
            "Breaker armed · book computable"
          )}
        </span>
      </div>

      <Row
        label="Day P&L vs anchor"
        value={
          risk.day_pnl === null
            ? "—"
            : `${risk.day_pnl > 0 ? "+" : ""}${money(risk.day_pnl)}${
                risk.day_pnl_pct !== null ? ` (${risk.day_pnl_pct.toFixed(2)}%)` : ""
              }`
        }
        detail={
          risk.day_anchor > 0
            ? `Anchor ${money(risk.day_anchor)} · breaker at −${risk.max_daily_dd_pct}%`
            : "Not yet anchored today — the breaker falls back to boot balance."
        }
      >
        {risk.day_pnl_pct !== null && <Meter pct={ddUsedPct} danger={ddUsedPct >= 100} />}
      </Row>

      <Row
        label="Book risk"
        value={
          risk.book_risk === null
            ? "un-computable"
            : `${money(risk.book_risk)}${
                risk.book_risk_pct !== null ? ` (${risk.book_risk_pct.toFixed(2)}%)` : ""
              }`
        }
        detail={`Portfolio cap ${risk.max_book_risk_pct}% of equity`}
      >
        {risk.book_risk_pct !== null && <Meter pct={bookUsedPct} danger={bookUsedPct >= 100} />}
      </Row>
    </div>
  );
}

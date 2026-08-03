import type { ReactNode } from "react";
import { ArrowUp, ArrowDown, Minus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Account, ArbiterBlock } from "@/lib/types";
import { money, signedPnl, pnlToneClass } from "@/lib/format";
import { cn } from "@/lib/utils";

function Tile({
  label,
  value,
  toneClass,
  testId,
  dataTone,
  icon,
  accent = false,
}: {
  label: string;
  value: string;
  toneClass?: string;
  testId?: string;
  dataTone?: string;
  icon?: ReactNode;
  accent?: boolean;
}) {
  return (
    <Card
      data-testid={testId}
      data-tone={dataTone}
      className={cn(
        // Resting depth, and on hover the border and shadow firm up. The lift
        // (hover:-translate-y-0.5) was removed deliberately: an operator scans
        // this KPI row constantly, and at that frequency a tile that springs
        // reads as noise. A dense trading dashboard should feel crisp, not
        // playful. Properties are named rather than transition-all so a later
        // className override cannot silently animate layout.
        "shadow-1 transition-[border-color,box-shadow] duration-fast hover:border-border-strong hover:shadow-2",
        // A hairline accent rail marks the primary live figure (Open P&L).
        accent && "border-l-2 border-l-accent"
      )}
    >
      <CardHeader className="pb-1 pt-4 px-4">
        <CardTitle className="text-xs font-medium text-muted-foreground tracking-wide uppercase font-sans">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className={cn("flex items-center gap-1.5 font-mono tabnum text-2xl font-semibold", toneClass)}>
          {icon}
          <span>{value}</span>
        </div>
      </CardContent>
    </Card>
  );
}

export function StatTiles({
  account,
  arbiter,
  dayPnl,
  openPnl,
  openCount,
  pendingCount = 0,
}: {
  account: Account;
  arbiter: ArbiterBlock;
  /**
   * Day P&L measured against the RISK-01 daily anchor, or null when the day is
   * not yet anchored. This used to be computed client-side as
   * `equity - account.balance`, but `balance` is latched once at the first
   * heartbeat after boot — so the tile actually showed floating P&L since
   * process start and silently re-based on every restart. null renders "—"
   * rather than a confident 0.00.
   */
  dayPnl: number | null;
  /** Live floating P&L summed across all open orders (Σ position.pnl). */
  openPnl: number;
  openCount: number;
  /** Resting LIMIT/STOP orders — committed risk that has not filled yet. */
  pendingCount?: number;
}) {
  const day = signedPnl(dayPnl ?? 0);
  const DayIcon = day.tone === "profit" ? ArrowUp : day.tone === "loss" ? ArrowDown : Minus;

  const open = signedPnl(openPnl);
  const OpenIcon = open.tone === "profit" ? ArrowUp : open.tone === "loss" ? ArrowDown : Minus;

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-6">
      <Tile label="Balance" value={money(account.balance)} testId="tile-balance" />
      <Tile label="Equity" value={money(account.equity)} testId="tile-equity" />
      <Tile
        label="Open P&L"
        value={open.text}
        toneClass={pnlToneClass(open.tone)}
        testId="tile-openpnl"
        dataTone={open.tone}
        icon={<OpenIcon className="size-4" aria-hidden />}
        accent
      />
      <Tile
        label="Day P&L"
        value={dayPnl === null ? "—" : day.text}
        toneClass={dayPnl === null ? undefined : pnlToneClass(day.tone)}
        testId="tile-daypnl"
        dataTone={dayPnl === null ? "unanchored" : day.tone}
        icon={dayPnl === null ? undefined : <DayIcon className="size-4" aria-hidden />}
      />
      {/* Positions AND resting orders: "0 open" alone hid two live limits. */}
      <Tile
        label="Open / Pending"
        value={`${openCount} / ${pendingCount}`}
        testId="tile-open-positions"
      />
      <Tile
        label="Arbiter Approved / Blocked"
        value={`${arbiter.stats.approved} / ${arbiter.stats.submitted - arbiter.stats.approved}`}
        testId="tile-arbiter"
      />
    </div>
  );
}

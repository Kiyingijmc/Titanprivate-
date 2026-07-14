import type { ReactNode } from "react";
import { ArrowUp, ArrowDown, Minus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Account, ArbiterBlock } from "@/lib/types";
import { money, signedPnl } from "@/lib/format";
import { cn } from "@/lib/utils";

function Tile({
  label,
  value,
  toneClass,
  testId,
  dataTone,
  icon,
}: {
  label: string;
  value: string;
  toneClass?: string;
  testId?: string;
  dataTone?: string;
  icon?: ReactNode;
}) {
  return (
    <Card data-testid={testId} data-tone={dataTone}>
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
  openCount,
}: {
  account: Account;
  arbiter: ArbiterBlock;
  dayPnl: number;
  openCount: number;
}) {
  const pnl = signedPnl(dayPnl);
  const pnlToneClass = {
    profit: "text-profit",
    loss: "text-loss",
    flat: "text-muted-foreground",
  }[pnl.tone];
  const PnlIcon = pnl.tone === "profit" ? ArrowUp : pnl.tone === "loss" ? ArrowDown : Minus;

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
      <Tile label="Balance" value={money(account.balance)} />
      <Tile label="Equity" value={money(account.equity)} />
      <Tile
        label="Day P&L"
        value={pnl.text}
        toneClass={pnlToneClass}
        testId="tile-daypnl"
        dataTone={pnl.tone}
        icon={<PnlIcon className="size-4" aria-hidden />}
      />
      <Tile label="Open Positions" value={String(openCount)} testId="tile-open-positions" />
      <Tile
        label="Arbiter Approved / Blocked"
        value={`${arbiter.stats.approved} / ${arbiter.stats.submitted - arbiter.stats.approved}`}
        testId="tile-arbiter"
      />
    </div>
  );
}

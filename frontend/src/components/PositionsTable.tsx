import { PositionDetails } from "@/components/PositionManagement";
import { X } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { SideChip } from "@/components/SideChip";
import type { Position } from "@/lib/types";
import { signedPnl, price, lots, pnlToneClass } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PositionsTable({
  positions,
  onClose,
  readOnly,
  blockedSymbols = {},
  stale = false,
}: {
  positions: Position[];
  onClose: (ticket: number) => void;
  readOnly: boolean;
  stale?: boolean;
  /** symbol -> human reason it is currently news-blocked (Task 6). Omitted by
   * an old caller or absent snapshot.news is equivalent to "nothing blocked". */
  blockedSymbols?: Record<string, string>;
}) {
  return (
    <Table className="whitespace-nowrap">
      <TableHeader className="[&_th]:text-secondary-foreground">
        <TableRow>
          <TableHead className="sticky left-0 z-10 bg-surface-1">Instrument</TableHead>
          <TableHead>Side</TableHead>
          <TableHead className="text-right">Lots</TableHead>
          <TableHead className="hidden lg:table-cell text-right">Entry</TableHead>
          <TableHead className="hidden lg:table-cell text-right">SL</TableHead>
          <TableHead className="hidden lg:table-cell text-right">TP</TableHead>
          <TableHead className="text-right">PnL</TableHead>
          <TableHead>Management</TableHead>
          <TableHead className="hidden xl:table-cell">Strategy</TableHead>
          <TableHead className="text-right">Close</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((p) => {
          const pnl = signedPnl(p.pnl);
          return (
            <TableRow key={p.ticket}>
              <TableCell className="sticky left-0 z-10 bg-surface-1">
                <span className="flex items-center gap-1.5 font-semibold">
                  <PositionDetails position={p} stale={stale} compact />
                  {blockedSymbols[p.symbol] && (
                    <Badge
                      data-testid="news-blocked-badge"
                      variant="outline"
                      title={blockedSymbols[p.symbol]}
                      className="border-transparent bg-blocked/15 text-blocked"
                    >
                      News
                    </Badge>
                  )}
                </span>
                <span className="mt-1 block font-mono text-xs text-secondary-foreground">#{p.ticket}</span>
              </TableCell>
              <TableCell>
                <SideChip side={p.side} />
              </TableCell>
              <TableCell className="text-right font-mono tabnum">{lots(p.lots)}</TableCell>
              <TableCell className="hidden lg:table-cell text-right font-mono tabnum">{price(p.entry)}</TableCell>
              <TableCell className="hidden lg:table-cell text-right font-mono tabnum">{p.sl > 0 ? price(p.sl) : <span className="text-warning">No stop</span>}</TableCell>
              <TableCell className="hidden lg:table-cell text-right font-mono tabnum">{p.tp > 0 ? price(p.tp) : <span className="text-secondary-foreground">No fixed TP</span>}</TableCell>
              <TableCell className={cn("text-right font-mono tabnum", pnlToneClass(pnl.tone))}>
                {pnl.text}
              </TableCell>
              <TableCell><PositionDetails position={p} stale={stale} /></TableCell>
              <TableCell className="hidden xl:table-cell"><span className="block">{p.strategy || "—"}</span><span className="text-xs text-secondary-foreground">{p.grade ? `Grade ${p.grade}` : "No grade"}</span></TableCell>
              <TableCell className="text-right">
                <button
                  type="button"
                  aria-label={`Close position ${p.ticket}`}
                  disabled={readOnly}
                  onClick={() => onClose(p.ticket)}
                  className={cn(
                    // Full 44px touch target; destructive action still requires confirmation.
                    "inline-flex h-11 w-11 items-center justify-center rounded-md border border-border",
                    "hover:bg-loss/15 hover:text-loss hover:border-loss/30",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    "disabled:opacity-50 disabled:pointer-events-none"
                  )}
                >
                  <X className="size-4" aria-hidden />
                </button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

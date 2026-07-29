import { X } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { SideChip } from "@/components/SideChip";
import type { Position } from "@/lib/types";
import { signedPnl, price, lots, pnlToneClass } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PositionsTable({
  positions,
  onClose,
  readOnly,
}: {
  positions: Position[];
  onClose: (ticket: number) => void;
  readOnly: boolean;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Ticket</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead className="text-right">Lots</TableHead>
          <TableHead className="text-right">Entry</TableHead>
          <TableHead className="text-right">SL</TableHead>
          <TableHead className="text-right">TP</TableHead>
          <TableHead className="text-right">PnL</TableHead>
          <TableHead>Grade</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead className="text-right">Close</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((p) => {
          const pnl = signedPnl(p.pnl);
          return (
            <TableRow key={p.ticket}>
              <TableCell className="font-mono tabnum">{p.ticket}</TableCell>
              <TableCell>{p.symbol}</TableCell>
              <TableCell>
                <SideChip side={p.side} />
              </TableCell>
              <TableCell className="text-right font-mono tabnum">{lots(p.lots)}</TableCell>
              <TableCell className="text-right font-mono tabnum">{price(p.entry)}</TableCell>
              <TableCell className="text-right font-mono tabnum">{price(p.sl)}</TableCell>
              <TableCell className="text-right font-mono tabnum">{price(p.tp)}</TableCell>
              <TableCell className={cn("text-right font-mono tabnum", pnlToneClass(pnl.tone))}>
                {pnl.text}
              </TableCell>
              <TableCell>{p.grade}</TableCell>
              <TableCell>{p.strategy}</TableCell>
              <TableCell className="text-right">
                <button
                  type="button"
                  aria-label={`Close position ${p.ticket}`}
                  disabled={readOnly}
                  onClick={() => onClose(p.ticket)}
                  className={cn(
                    // 36px hit target (up from ~28px) — closer to the 44px touch min
                    // without forcing tall rows in a dense desktop/tablet table.
                    "inline-flex h-9 w-9 items-center justify-center rounded-md border border-border",
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

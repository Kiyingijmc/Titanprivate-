import { X, AlertTriangle } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { SideChip } from "@/components/SideChip";
import { Badge } from "@/components/ui/badge";
import type { PendingOrder } from "@/lib/types";
import { price, lots } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Resting LIMIT/STOP orders. These were invisible everywhere in the GUI until
 * 2026-08-02 even though the heartbeat has always carried them: the operator saw
 * "Open Positions 0" while MT5 held two live limits.
 *
 * The `tracked` column is the reason this table earns its place. An order Titan
 * did not place has no state-DB row, so it has no stop the book-wide risk cap can
 * price — and aggregate_open_risk therefore does not count it at all. That order
 * is real exposure the cap is blind to, so it must not render like a managed one.
 */
export function PendingOrdersTable({
  orders,
  onCancel,
  readOnly,
}: {
  orders: PendingOrder[];
  onCancel: (ticket: number) => void;
  readOnly: boolean;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Ticket</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">Lots</TableHead>
          <TableHead className="text-right">Price</TableHead>
          <TableHead className="text-right">SL</TableHead>
          <TableHead className="text-right">TP</TableHead>
          <TableHead>Grade</TableHead>
          <TableHead>Strategy</TableHead>
          <TableHead className="text-right">Cancel</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((o) => (
          <TableRow
            key={o.ticket}
            data-testid={`pending-row-${o.ticket}`}
            data-tracked={o.tracked}
            // A warning rail, not a red row: the order is not an error, it is
            // simply outside Titan's risk accounting.
            className={cn(!o.tracked && "border-l-2 border-l-blocked bg-blocked/5")}
          >
            <TableCell className="font-mono tabnum">{o.ticket}</TableCell>
            <TableCell>
              <span className="flex items-center gap-1.5">
                {o.symbol}
                {!o.tracked && (
                  <Badge
                    variant="outline"
                    data-testid={`untracked-badge-${o.ticket}`}
                    className="shrink-0 gap-1 border-blocked/40 bg-blocked/15 text-blocked"
                    title="No state-DB row: placed outside Titan. It carries no stop the portfolio risk cap can price, so the cap does not count it."
                  >
                    <AlertTriangle className="size-3" aria-hidden />
                    Untracked
                  </Badge>
                )}
              </span>
            </TableCell>
            <TableCell>{o.side === "?" ? "?" : <SideChip side={o.side} />}</TableCell>
            <TableCell className="text-muted-foreground">{o.kind}</TableCell>
            <TableCell className="text-right font-mono tabnum">{lots(o.lots)}</TableCell>
            <TableCell className="text-right font-mono tabnum">{price(o.price)}</TableCell>
            <TableCell
              className={cn(
                "text-right font-mono tabnum",
                o.sl === 0 && "text-blocked"
              )}
            >
              {/* An em dash, never "0" — a stop of zero is absent, not at price 0. */}
              {o.sl === 0 ? "—" : price(o.sl)}
            </TableCell>
            <TableCell className="text-right font-mono tabnum">
              {o.tp === 0 ? "—" : price(o.tp)}
            </TableCell>
            <TableCell>{o.grade}</TableCell>
            <TableCell>{o.strategy}</TableCell>
            <TableCell className="text-right">
              <button
                type="button"
                aria-label={`Cancel order ${o.ticket}`}
                disabled={readOnly}
                onClick={() => onCancel(o.ticket)}
                className={cn(
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
        ))}
      </TableBody>
    </Table>
  );
}

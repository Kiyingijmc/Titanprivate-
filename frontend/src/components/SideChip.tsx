import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * BUY/SELL direction chip — profit-tone for BUY, loss-tone for SELL, always
 * carrying `data-tone` for tests. Shared by PositionsTable and the Overview
 * top-positions list so the mapping lives in exactly one place.
 */
export function SideChip({ side }: { side: "BUY" | "SELL" }) {
  const tone = side === "BUY" ? "profit" : "loss";
  return (
    <Badge
      variant="outline"
      data-tone={tone}
      className={cn(
        "border-transparent",
        tone === "profit" ? "bg-profit/15 text-profit" : "bg-loss/15 text-loss"
      )}
    >
      {side}
    </Badge>
  );
}

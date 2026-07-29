import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type PositionsSide = "ALL" | "BUY" | "SELL";
export type PositionsSort = "pnl" | "symbol" | "lots";

export interface PositionsFilterState {
  symbol: string;
  side: PositionsSide;
  sort: PositionsSort;
}

const selectClass = cn(
  "flex h-10 items-center rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground",
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  "disabled:cursor-not-allowed disabled:opacity-50"
);

/**
 * Filter/sort bar for the Positions page (design-system §6): a free-text
 * symbol filter, a BUY/SELL/All side filter, and a pnl/symbol/lots sort —
 * fully controlled so PositionsPage owns the state and applies it in a
 * single useMemo alongside PositionsTable.
 */
export function PositionsFilters({
  value,
  onChange,
}: {
  value: PositionsFilterState;
  onChange: (next: PositionsFilterState) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="positions-filter-symbol" className="sr-only">
        Filter by symbol
      </label>
      <Input
        id="positions-filter-symbol"
        aria-label="Filter by symbol"
        placeholder="Filter by symbol…"
        value={value.symbol}
        onChange={(e) => onChange({ ...value, symbol: e.target.value })}
        className="h-9 max-w-[200px]"
      />

      <label htmlFor="positions-filter-side" className="sr-only">
        Side
      </label>
      <select
        id="positions-filter-side"
        aria-label="Side"
        value={value.side}
        onChange={(e) => onChange({ ...value, side: e.target.value as PositionsSide })}
        className={cn(selectClass, "h-9 w-auto")}
      >
        <option value="ALL">All sides</option>
        <option value="BUY">Buy</option>
        <option value="SELL">Sell</option>
      </select>

      <label htmlFor="positions-filter-sort" className="sr-only">
        Sort by
      </label>
      <select
        id="positions-filter-sort"
        aria-label="Sort by"
        value={value.sort}
        onChange={(e) => onChange({ ...value, sort: e.target.value as PositionsSort })}
        className={cn(selectClass, "h-9 w-auto")}
      >
        <option value="pnl">Sort: PnL</option>
        <option value="symbol">Sort: Symbol</option>
        <option value="lots">Sort: Lots</option>
      </select>
    </div>
  );
}

import { useMemo, useState } from "react";
import { Ban } from "lucide-react";
import { Panel, type PanelStatus } from "@/components/shell/Panel";
import { PositionsTable } from "@/components/PositionsTable";
import { PositionsFilters, type PositionsFilterState } from "@/components/PositionsFilters";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useController } from "@/context/ControllerContext";
import { useReadOnly } from "@/context/ReadOnlyContext";
import { useMutate } from "@/lib/useMutation";
import type { Position } from "@/lib/types";

const DEFAULT_FILTERS: PositionsFilterState = { symbol: "", side: "ALL", sort: "pnl" };

function applyFilters(positions: Position[], filters: PositionsFilterState): Position[] {
  const symbolQuery = filters.symbol.trim().toLowerCase();
  const filtered = positions.filter((p) => {
    if (symbolQuery && !p.symbol.toLowerCase().includes(symbolQuery)) return false;
    if (filters.side !== "ALL" && p.side !== filters.side) return false;
    return true;
  });
  return filtered.sort((a, b) => {
    if (filters.sort === "symbol") return a.symbol.localeCompare(b.symbol);
    if (filters.sort === "lots") return b.lots - a.lots;
    return b.pnl - a.pnl;
  });
}

/**
 * Positions section (design-system §6): a filter/sort bar above
 * PositionsTable, per-row close and a destructive Close All — both routed
 * through useMutate (403 -> read-only banner) and gated behind an
 * AlertDialog confirm. Panel status reflects the *unfiltered* snapshot so a
 * filter that matches nothing renders an empty table, not the empty-state
 * message (that's reserved for zero real positions).
 */
export default function PositionsPage() {
  const { snapshot, connectionStatus, api } = useController();
  const { readOnly } = useReadOnly();
  const { run } = useMutate();

  const [filters, setFilters] = useState<PositionsFilterState>(DEFAULT_FILTERS);
  const [pendingClose, setPendingClose] = useState<number | null>(null);
  const [closeAllPending, setCloseAllPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const positions = snapshot?.positions ?? [];
  const filtered = useMemo(() => applyFilters(positions, filters), [positions, filters]);

  const status: PanelStatus =
    snapshot === null
      ? "loading"
      : connectionStatus.stale
        ? "stale"
        : positions.length === 0
          ? "empty"
          : "populated";

  async function confirmClose() {
    const ticket = pendingClose;
    setPendingClose(null);
    if (ticket === null) return;
    setError(null);
    const result = await run(() => api.postCommand({ command: "close", ticket }));
    if (!result.ok && result.error !== "read-only") {
      setError(`close ${ticket}: ${result.error}`);
    }
  }

  async function confirmCloseAll() {
    setCloseAllPending(false);
    setError(null);
    const result = await run(() => api.postCommand({ command: "closeall", confirm: true }));
    if (!result.ok && result.error !== "read-only") {
      setError(`close all: ${result.error}`);
    }
  }

  return (
    <div className="grid gap-4">
      <Panel
        status={status}
        title="Positions"
        emptyMessage="No open positions"
        actions={
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={readOnly || positions.length === 0}
            onClick={() => setCloseAllPending(true)}
          >
            <Ban aria-hidden /> Close All
          </Button>
        }
      >
        <div className="grid gap-3">
          <PositionsFilters value={filters} onChange={setFilters} />
          {error && (
            <div role="alert" className="text-sm text-loss">
              {error}
            </div>
          )}
          <PositionsTable
            positions={filtered}
            onClose={(ticket) => setPendingClose(ticket)}
            readOnly={readOnly}
          />
        </div>
      </Panel>

      <AlertDialog open={pendingClose !== null} onOpenChange={(open) => !open && setPendingClose(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Close position {pendingClose}?</AlertDialogTitle>
            <AlertDialogDescription>
              This immediately closes the position. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmClose}>Confirm</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={closeAllPending} onOpenChange={setCloseAllPending}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Close all positions?</AlertDialogTitle>
            <AlertDialogDescription>
              This immediately closes every open position. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmCloseAll}>Confirm</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

import { useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { Api, ApiError } from "@/lib/api";
import type { RegistryRow } from "@/lib/types";
import { cn } from "@/lib/utils";

function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null && "kind" in e;
}

type Tone = "info" | "warning" | "profit" | "secondary";

function toneFor(value: string): Tone {
  const v = value.toLowerCase();
  if (v === "live") return "info";
  if (v === "research") return "warning";
  if (v === "active") return "profit";
  return "secondary";
}

const TONE_CLASS: Record<Tone, string> = {
  info: "bg-info/15 text-info",
  warning: "bg-warning/15 text-warning",
  profit: "bg-profit/15 text-profit",
  secondary: "bg-muted text-muted-foreground",
};

function ToneBadge({ value }: { value: string }) {
  return (
    <Badge variant="outline" className={cn("border-transparent", TONE_CLASS[toneFor(value)])}>
      {value}
    </Badge>
  );
}

/**
 * Promote gate mirrors the backend's typed-id confirm: the operator must type
 * the exact strategy id before "Confirm promote" enables, then we POST
 * registryAction(id, "promote", { confirm: id }) — see design-system §6.
 */
function PromoteDialog({
  row,
  api,
  readOnly,
  onDone,
  onError,
}: {
  row: RegistryRow;
  api: Api;
  readOnly: boolean;
  onDone: () => void;
  onError: (e: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const canConfirm = typed === row.id;
  const inputId = `promote-typed-${row.id}`;

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) setTyped("");
  }

  async function confirm() {
    try {
      await api.registryAction(row.id, "promote", { confirm: row.id });
      onOpenChange(false);
      onDone();
    } catch (e) {
      onError(e);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm" disabled={readOnly}>
          Promote
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Promote {row.id}</DialogTitle>
          <DialogDescription>
            Type the strategy id to confirm promoting &quot;{row.id}&quot; from research to live.
          </DialogDescription>
        </DialogHeader>
        <label htmlFor={inputId} className="text-sm text-muted-foreground">
          Type the strategy id
        </label>
        <Input
          id={inputId}
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={row.id}
          autoComplete="off"
        />
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!canConfirm} onClick={confirm}>
            Confirm promote
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Registry table per design-system §6: status badges (live=info, research=
 * warning, ACTIVE=profit), enable/disable, and a typed-id-gated promote
 * dialog. Research rows get a warning left border. All mutations are
 * disabled in read-only mode.
 */
export function StrategiesTab({
  api,
  readOnly,
  onReadOnly,
}: {
  api: Api;
  readOnly: boolean;
  onReadOnly?: () => void;
}) {
  const [rows, setRows] = useState<RegistryRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    api.getRegistry().then(setRows).catch(() => {
      /* keep the last known table rather than crash */
    });
  }

  useEffect(() => {
    let cancelled = false;
    api
      .getRegistry()
      .then((r) => {
        if (!cancelled) setRows(r);
      })
      .catch(() => {
        /* leave the table empty rather than crash on a failed load */
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  function handleError(prefix: string, e: unknown) {
    if (isApiError(e) && e.kind === "readOnly") onReadOnly?.();
    setError(isApiError(e) ? `${prefix}: ${e.detail}` : `${prefix} failed`);
  }

  async function act(id: string, action: "enable" | "disable") {
    setError(null);
    try {
      await api.registryAction(id, action);
      reload();
    } catch (e) {
      handleError(`${action} ${id}`, e);
    }
  }

  return (
    <div className="space-y-3">
      {error && (
        <div role="alert" className="text-sm text-loss">
          {error}
        </div>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Id</TableHead>
            <TableHead>Version</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>State</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow
              key={row.id}
              className={cn(row.status === "research" && "border-l-2 border-l-warning")}
            >
              <TableCell className="font-mono">{row.id}</TableCell>
              <TableCell className="font-mono tabnum">{row.version}</TableCell>
              <TableCell>
                <ToneBadge value={row.status} />
              </TableCell>
              <TableCell>
                <ToneBadge value={row.state} />
              </TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={readOnly}
                    onClick={() => act(row.id, "enable")}
                  >
                    Enable
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={readOnly}
                    onClick={() => act(row.id, "disable")}
                  >
                    Disable
                  </Button>
                  <PromoteDialog
                    row={row}
                    api={api}
                    readOnly={readOnly}
                    onDone={reload}
                    onError={(e) => handleError(`promote ${row.id}`, e)}
                  />
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

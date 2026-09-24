import { useCallback, useEffect, useRef, useState } from "react";
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
import { Panel } from "@/components/shell/Panel";
import { RefreshCw, Search } from "lucide-react";

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
  onDone: (response?: string) => void;
  onError: (e: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canConfirm = typed === row.id;
  const inputId = `promote-typed-${row.id}`;

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) { setTyped(""); setError(null); }
  }

  async function confirm() {
    if (busy || readOnly || !canConfirm) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.registryAction(row.id, "promote", { confirm: row.id });
      onOpenChange(false);
      onDone(typeof response.result === "string" ? response.result : undefined);
    } catch (e) {
      setError(isApiError(e) ? e.detail : "Promotion failed. Please try again.");
      onError(e);
    } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm" disabled={readOnly}>
          Promote
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] w-[calc(100%-2rem)] overflow-y-auto rounded-lg">
        <DialogHeader>
          <DialogTitle>Promote {row.id}</DialogTitle>
          <DialogDescription>
            Type the strategy id to request live enablement of &quot;{row.id}&quot;, including permission to run a research strategy.
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
        {error && <p role="alert" className="text-sm text-loss">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!canConfirm || readOnly || busy} onClick={confirm}>
            {busy ? "Submitting…" : "Confirm promote"}
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
  const [rows, setRows] = useState<RegistryRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [classification, setClassification] = useState("all");
  const [pending, setPending] = useState<string | null>(null);
  const generation = useRef(0);
  const actionBusy = useRef(false);

  const reload = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setLoadError(false);
    try {
      const result = await api.getRegistry();
      if (request === generation.current) setRows(result);
    } catch {
      if (request === generation.current) setLoadError(true);
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    setRows(null);
    void reload();
    return () => { generation.current++; };
  }, [reload]);

  function handleError(prefix: string, e: unknown) {
    if (isApiError(e) && e.kind === "readOnly") onReadOnly?.();
    setError(isApiError(e) ? `${prefix}: ${e.detail}` : `${prefix} failed`);
  }

  async function act(id: string, action: "enable" | "disable") {
    if (readOnly || actionBusy.current) return;
    actionBusy.current = true;
    setPending(id);
    setError(null);
    setResponse(null);
    try {
      const result = await api.registryAction(id, action);
      if (typeof result.result === "string") setResponse(result.result);
      await reload();
    } catch (e) {
      handleError(`${action} ${id}`, e);
    } finally {
      actionBusy.current = false;
      setPending(null);
    }
  }

  const all = rows ?? [];
  const filtered = all.filter(row =>
    row.id.toLowerCase().includes(query.trim().toLowerCase()) &&
    (classification === "all" || row.status.toLowerCase() === classification));
  const summary = [
    ["Registered strategies", all.length],
    ["Active instances", all.filter(row => row.state.toUpperCase() === "ACTIVE").length],
    ["Live classification", all.filter(row => row.status.toLowerCase() === "live").length],
    ["Research classification", all.filter(row => row.status.toLowerCase() === "research").length],
  ];

  return (
    <div className="grid min-w-0 gap-5">
      <section aria-label="Strategy summary" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {summary.map(([label, count]) => <div key={label} className="rounded-lg border border-border bg-surface-1 p-4">
          <p className="text-xs text-secondary-foreground">{label}</p>
          <p className="mt-2 font-mono text-2xl tabnum">{rows === null ? "—" : count}</p>
          {loadError && rows !== null && <p className="mt-1 text-xs text-warning">Last received registry</p>}
        </div>)}
      </section>
      <Panel status={rows === null ? (loadError ? "error" : "loading") : loadError ? "stale" : "populated"}
        title="Strategies" domain="execution" className="min-w-0"
        onRetry={() => void reload()} errorMessage="Could not load the strategy registry."
        actions={<Button variant="outline" size="sm" disabled={loading} onClick={() => void reload()}><RefreshCw aria-hidden />{loading ? "Refreshing…" : "Refresh"}</Button>}>
        <div className="space-y-4">
          {loadError && <p role="alert" className="text-sm text-warning">Refresh failed. Showing the last received registry; changes may not be reflected.</p>}
          {response && <p role="status" className="rounded-lg border border-border bg-surface-2 p-3 text-sm text-secondary-foreground">{response}</p>}
          {error && <p role="alert" className="text-sm text-loss">{error}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full sm:max-w-xs"><Search className="pointer-events-none absolute left-3 top-3 size-4 text-secondary-foreground" aria-hidden /><Input aria-label="Search strategies" placeholder="Search strategies…" value={query} onChange={e => setQuery(e.target.value)} className="h-11 pl-9" /></div>
            <select aria-label="Strategy classification" value={classification} onChange={e => setClassification(e.target.value)} className="h-11 rounded-md border border-border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <option value="all">All classifications</option><option value="live">Live</option><option value="research">Research</option>
            </select>
            <span className="text-xs text-secondary-foreground">{filtered.length} of {all.length} strategies</span>
            {(query || classification !== "all") && <Button variant="ghost" size="sm" onClick={() => { setQuery(""); setClassification("all"); }}>Reset filters</Button>}
          </div>
          {all.length === 0 ? <p className="py-6 text-center text-sm text-secondary-foreground">No strategies registered.</p> : filtered.length === 0 ? <p role="status" className="py-6 text-center text-sm text-secondary-foreground">No strategies match these filters.</p> :
          <Table className="whitespace-nowrap">
            <TableHeader className="[&_th]:text-secondary-foreground"><TableRow>
              <TableHead className="sticky left-0 z-10 bg-surface-1">Strategy</TableHead><TableHead>Classification</TableHead><TableHead>Runtime</TableHead><TableHead>Timeframe</TableHead><TableHead>Priority</TableHead><TableHead className="text-right">Actions</TableHead>
            </TableRow></TableHeader>
            <TableBody>{filtered.map(row => <TableRow key={row.id} className={cn(row.status === "research" && "border-l-2 border-l-warning")}>
              <TableCell className="sticky left-0 z-10 bg-surface-1"><span className="font-medium">{row.id}</span><span className="mt-1 block font-mono text-xs text-secondary-foreground">v{row.version}</span></TableCell>
              <TableCell><ToneBadge value={row.status} /></TableCell><TableCell><ToneBadge value={row.state} /></TableCell>
              <TableCell className="font-mono">{row.tf ?? "—"}</TableCell><TableCell className="font-mono">{row.priority ?? "—"}</TableCell>
              <TableCell className="text-right"><div className="flex justify-end gap-2" aria-busy={pending === row.id}>
                <Button variant="outline" size="sm" disabled={readOnly || pending !== null} onClick={() => void act(row.id, "enable")}>Enable</Button>
                <Button variant="outline" size="sm" disabled={readOnly || pending !== null} onClick={() => void act(row.id, "disable")}>Disable</Button>
                <PromoteDialog row={row} api={api} readOnly={readOnly || pending !== null} onDone={message => { setResponse(message ?? null); void reload(); }} onError={e => handleError(`promote ${row.id}`, e)} />
              </div></TableCell>
            </TableRow>)}</TableBody>
          </Table>}
          <p className="text-xs leading-relaxed text-secondary-foreground">Classification and runtime state are separate. A live classification does not guarantee an order: entry conditions, market availability, and account controls still apply.</p>
        </div>
      </Panel>
    </div>
  );
}

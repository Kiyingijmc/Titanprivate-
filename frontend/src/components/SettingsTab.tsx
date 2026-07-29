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
import type { Api, ApiError } from "@/lib/api";
import type { SettingRow } from "@/lib/types";
import { cn } from "@/lib/utils";

function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null && "kind" in e;
}

function stringifyValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function parseValue(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function SourceBadge({ source }: { source: string }) {
  const isOverride = source === "override";
  return (
    <Badge
      variant="outline"
      className={cn(
        "border-transparent",
        isOverride ? "bg-info/15 text-info" : "bg-muted text-muted-foreground"
      )}
    >
      {source}
    </Badge>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const isRestart = tier === "restart";
  return (
    <Badge
      variant="outline"
      className={cn("border-transparent", isRestart ? "bg-warning/15 text-warning" : "bg-profit/15 text-profit")}
    >
      {isRestart ? "restart-required" : "live"}
    </Badge>
  );
}

/** First dotted segment of a setting key — its domain (signal_grading / risk / connection / …). */
function domainOf(key: string): string {
  const idx = key.indexOf(".");
  return idx === -1 ? key : key.slice(0, idx);
}

function ColumnHeader() {
  return (
    <TableHeader>
      <TableRow>
        <TableHead>Key</TableHead>
        <TableHead>Value</TableHead>
        <TableHead>Source</TableHead>
        <TableHead>Tier</TableHead>
        <TableHead className="text-right">Save</TableHead>
      </TableRow>
    </TableHeader>
  );
}

/**
 * Settings table per design-system §6: source badge (default/override) +
 * tier badge (live=profit, restart=warning "restart-required"). Editing a
 * value + Save calls patchSetting; a 422 (ApiError.kind==="validation")
 * renders its detail inline under the row; success shows applied/
 * restart_required. All mutations disabled in read-only mode.
 *
 * Optional `filter` (substring match on key, case-insensitive) and
 * `groupByDomain` (split rows into per-domain tables with a heading) let a
 * page compose a searchable/grouped view without reimplementing the
 * source/tier/patch/422 logic — SettingsPage is the current consumer.
 */
export function SettingsTab({
  api,
  readOnly,
  filter = "",
  groupByDomain = false,
}: {
  api: Api;
  readOnly: boolean;
  filter?: string;
  groupByDomain?: boolean;
}) {
  const [rows, setRows] = useState<SettingRow[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    api
      .getSettings()
      .then((r) => {
        if (cancelled) return;
        setRows(r);
        setDrafts(Object.fromEntries(r.map((row) => [row.key, stringifyValue(row.value)])));
      })
      .catch(() => {
        /* leave the table empty rather than crash on a failed load */
      });
    return () => {
      cancelled = true;
    };
  }, [api]);

  async function save(row: SettingRow) {
    setErrors((e) => ({ ...e, [row.key]: "" }));
    setMessages((m) => ({ ...m, [row.key]: "" }));
    try {
      const result = await api.patchSetting(row.key, parseValue(drafts[row.key] ?? ""));
      const msg = result.restart_required
        ? "Applied — restart required to take effect"
        : "Applied";
      setMessages((m) => ({ ...m, [row.key]: msg }));
    } catch (e) {
      const detail = isApiError(e) ? e.detail : "Save failed";
      setErrors((er) => ({ ...er, [row.key]: detail }));
    }
  }

  function renderRows(rowsToRender: SettingRow[]) {
    return rowsToRender.map((row) => {
      const inputId = `setting-${row.key}`;
      return (
        <TableRow key={row.key}>
          <TableCell className="font-mono">
            <label htmlFor={inputId}>{row.key}</label>
          </TableCell>
          <TableCell>
            <Input
              id={inputId}
              value={drafts[row.key] ?? ""}
              disabled={readOnly}
              onChange={(e) => setDrafts((d) => ({ ...d, [row.key]: e.target.value }))}
            />
            {errors[row.key] && (
              <div role="alert" className="mt-1 text-sm text-loss">
                {errors[row.key]}
              </div>
            )}
            {messages[row.key] && (
              <div role="status" className="mt-1 text-sm text-profit">
                {messages[row.key]}
              </div>
            )}
          </TableCell>
          <TableCell>
            <SourceBadge source={row.source} />
          </TableCell>
          <TableCell>
            <TierBadge tier={row.tier} />
          </TableCell>
          <TableCell className="text-right">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={readOnly}
              onClick={() => save(row)}
            >
              Save
            </Button>
          </TableCell>
        </TableRow>
      );
    });
  }

  const query = filter.trim().toLowerCase();
  const filteredRows = query ? rows.filter((row) => row.key.toLowerCase().includes(query)) : rows;

  if (!groupByDomain) {
    return (
      <Table>
        <ColumnHeader />
        <TableBody>{renderRows(filteredRows)}</TableBody>
      </Table>
    );
  }

  const domainOrder: string[] = [];
  const domainGroups = new Map<string, SettingRow[]>();
  for (const row of filteredRows) {
    const domain = domainOf(row.key);
    if (!domainGroups.has(domain)) {
      domainGroups.set(domain, []);
      domainOrder.push(domain);
    }
    domainGroups.get(domain)!.push(row);
  }

  return (
    <div className="grid gap-4">
      {domainOrder.map((domain) => (
        <div key={domain}>
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {domain}
          </h3>
          <Table>
            <ColumnHeader />
            <TableBody>{renderRows(domainGroups.get(domain)!)}</TableBody>
          </Table>
        </div>
      ))}
    </div>
  );
}

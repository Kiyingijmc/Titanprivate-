import * as React from "react";
import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Wallet,
  Boxes,
  Activity as ActivityIcon,
  Settings as SettingsIcon,
  Search,
  Lock,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useReadOnly } from "@/context/ReadOnlyContext";

/** One entry in the palette's "Actions" group — supplied by the shell (Plan 2 wires the real handlers). */
export interface PaletteAction {
  id: string;
  label: string;
  run: () => void;
  destructive?: boolean;
  disabled?: boolean;
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  actions: PaletteAction[];
}

interface NavEntry {
  path: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ENTRIES: NavEntry[] = [
  { path: "/overview", label: "Overview", icon: LayoutDashboard },
  { path: "/positions", label: "Positions", icon: Wallet },
  { path: "/strategies", label: "Strategies", icon: Boxes },
  { path: "/activity", label: "Activity", icon: ActivityIcon },
  { path: "/settings", label: "Settings", icon: SettingsIcon },
];

const GROUP_HEADING_CLASS =
  "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs " +
  "[&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide " +
  "[&_[cmdk-group-heading]]:text-muted-foreground";

const ITEM_BASE_CLASS = cn(
  "flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors",
  "aria-selected:bg-surface-2",
  "data-[disabled=true]:cursor-not-allowed data-[disabled=true]:opacity-50 data-[disabled=true]:pointer-events-none"
);

/**
 * ⌘K command palette shell (design-system §4.3). Delivers the palette chrome + the fixed
 * Navigate group + a read-only-aware `actions` contract; Plan 2 supplies real action handlers
 * (pause/close-all/panic/promote) and wires read-only into each action's `disabled` flag.
 */
export function CommandPalette({ open, onOpenChange, actions }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { readOnly } = useReadOnly();

  function go(path: string) {
    navigate(path);
    onOpenChange(false);
  }

  function runAction(action: PaletteAction) {
    if (action.disabled) return;
    action.run();
    onOpenChange(false);
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      overlayClassName="fixed inset-0 z-50 bg-background/80"
      contentClassName={cn(
        "fixed left-1/2 top-24 z-50 w-full max-w-lg -translate-x-1/2",
        "overflow-hidden rounded-lg border border-border bg-elevated shadow-2"
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-3">
        <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <Command.Input
          autoFocus
          placeholder="Search sections and actions..."
          className={cn(
            "h-11 w-full bg-transparent text-sm text-foreground outline-none",
            "placeholder:text-muted-foreground"
          )}
        />
        {readOnly && (
          <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
            <Lock className="size-3" aria-hidden="true" />
            Read-only
          </span>
        )}
      </div>

      <Command.List className="max-h-80 overflow-y-auto p-2">
        <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
          No results found.
        </Command.Empty>

        <Command.Group heading="Navigate" className={GROUP_HEADING_CLASS}>
          {NAV_ENTRIES.map(({ path, label, icon: Icon }) => (
            <Command.Item
              key={path}
              value={label}
              onSelect={() => go(path)}
              className={cn(ITEM_BASE_CLASS, "text-foreground")}
            >
              <Icon className="size-4 shrink-0 text-accent" aria-hidden="true" />
              <span>{label}</span>
            </Command.Item>
          ))}
        </Command.Group>

        {actions.length > 0 && (
          <Command.Group heading="Actions" className={GROUP_HEADING_CLASS}>
            {actions.map((action) => (
              <Command.Item
                key={action.id}
                value={action.label}
                disabled={action.disabled}
                onSelect={() => runAction(action)}
                title={action.disabled ? "Unavailable right now" : undefined}
                className={cn(ITEM_BASE_CLASS, action.destructive ? "text-loss" : "text-foreground")}
              >
                <span>{action.label}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  );
}

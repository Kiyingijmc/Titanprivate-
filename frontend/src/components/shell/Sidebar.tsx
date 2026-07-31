import * as React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Wallet,
  Boxes,
  Activity as ActivityIcon,
  Settings as SettingsIcon,
  FlaskConical,
  BookText,
  PanelLeftClose,
  PanelLeftOpen,
  Lock,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useReadOnly } from "@/context/ReadOnlyContext";
import { Logo } from "@/brand/Logo";

export interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/overview", label: "Overview", icon: LayoutDashboard },
  { to: "/positions", label: "Positions", icon: Wallet },
  { to: "/strategies", label: "Strategies", icon: Boxes },
  { to: "/activity", label: "Activity", icon: ActivityIcon },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

const DISABLED_ITEMS: NavItem[] = [
  { to: "/research", label: "Research", icon: FlaskConical },
  { to: "/journal", label: "Journal", icon: BookText },
];

function NavItemLink({ to, label, icon: Icon, collapsed }: NavItem & { collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      aria-label={label}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          isActive
            ? "bg-accent-subtle text-foreground"
            : "text-muted-foreground hover:bg-surface-2 hover:text-foreground"
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden="true"
            className={cn(
              "absolute left-0 top-1 bottom-1 w-0.5 rounded-full bg-accent transition-opacity",
              isActive ? "opacity-100" : "opacity-0"
            )}
          />
          <Icon className="size-4 shrink-0 text-accent" />
          {!collapsed && <span className="truncate">{label}</span>}
        </>
      )}
    </NavLink>
  );
}

function DisabledNavItem({ label, icon: Icon, collapsed }: NavItem & { collapsed: boolean }) {
  return (
    <div
      aria-disabled="true"
      title="Phase 2"
      className={cn(
        "flex cursor-not-allowed items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
        "pointer-events-none text-muted-foreground/50"
      )}
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </div>
  );
}

export function Sidebar({ collapsed, onToggleCollapse }: SidebarProps) {
  const { readOnly } = useReadOnly();

  return (
    <aside
      // The collapse is instant on purpose. This <aside> is in flow, so its
      // width IS the width of <main> — transitioning it relayouts and repaints
      // the whole dashboard (Recharts equity chart + positions table) on every
      // frame of the animation. The obvious alternative, a transform-based
      // collapse, does not apply here: a translated element keeps its layout
      // box, so main would never reclaim the space. Between animating layout on
      // a live trading view and snapping, snapping wins — this is a deliberate,
      // low-frequency action where the operator is looking at the result, and
      // an instant result is never "slow". Width and labels change in the same
      // frame, so there is no half-collapsed state to look wrong.
      className={cn(
        "flex h-full flex-col border-r border-border bg-surface-1",
        collapsed ? "w-16" : "w-60"
      )}
    >
      <div className={cn("flex items-center px-3 py-4", collapsed ? "justify-center" : "justify-start")}>
        <Logo variant={collapsed ? "mark" : "full"} className="h-6" />
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-2" aria-label="Sections">
        {NAV_ITEMS.map((item) => (
          <NavItemLink key={item.to} {...item} collapsed={collapsed} />
        ))}
        {DISABLED_ITEMS.map((item) => (
          <DisabledNavItem key={item.to} {...item} collapsed={collapsed} />
        ))}
      </nav>

      <div className="flex flex-col gap-2 border-t border-border px-2 py-3">
        {readOnly && (
          <div
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2 py-1 text-xs text-secondary-foreground",
              collapsed && "justify-center"
            )}
          >
            <Lock className="size-3 shrink-0" />
            {!collapsed && <span>Read-only</span>}
          </div>
        )}

        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(
            "inline-flex items-center gap-2 rounded-md px-2 py-2 text-sm text-muted-foreground",
            "hover:bg-surface-2 hover:text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            collapsed ? "justify-center" : "justify-start"
          )}
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  );
}

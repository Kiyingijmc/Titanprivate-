import { NavLink } from "react-router-dom";
import { LayoutDashboard, Wallet, Activity } from "lucide-react";
import { cn } from "@/lib/utils";

// Phone "glance" nav (design system §6.3): only the read-only glance sections.
const GLANCE = [
  { to: "/overview", label: "Overview", Icon: LayoutDashboard },
  { to: "/positions", label: "Positions", Icon: Wallet },
  { to: "/activity", label: "Activity", Icon: Activity },
];

/**
 * Fixed bottom tab bar shown only on phone widths (the sidebar is hidden there).
 * Exposes the glance sections; full control lives on desktop/tablet.
 */
export function BottomTabs({ className }: { className?: string }) {
  return (
    <nav
      aria-label="Primary"
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 flex h-16 items-stretch border-t border-border bg-surface-1",
        className
      )}
    >
      {GLANCE.map(({ to, label, Icon }) => (
        <NavLink
          key={to}
          to={to}
          aria-label={label}
          className={({ isActive }) =>
            cn(
              "flex flex-1 flex-col items-center justify-center gap-1 text-xs",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              isActive ? "text-accent" : "text-muted-foreground"
            )
          }
        >
          <Icon className="size-5" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

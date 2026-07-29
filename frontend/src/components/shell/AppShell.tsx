import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { StatusBar } from "@/components/shell/StatusBar";
import { CommandPalette, type PaletteAction } from "@/components/shell/CommandPalette";
import { useController } from "@/context/ControllerContext";

const SIDEBAR_COLLAPSED_KEY = "titan.sidebar.collapsed";

function readStoredCollapsed(): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false; // localStorage unavailable (private mode, SSR, etc.)
  }
}

/**
 * The shell layout (design system §4): Sidebar + StatusBar + routed <main> + CommandPalette.
 * Owns sidebar-collapsed (persisted) and palette-open (⌘K + StatusBar trigger) state; reads
 * live data from ControllerContext (provided by App). Real command wiring lands in Plan 2 —
 * `actions` is intentionally empty here.
 */
export function AppShell() {
  const { snapshot, connectionStatus } = useController();
  const [collapsed, setCollapsed] = useState<boolean>(readStoredCollapsed);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const mainRef = useRef<HTMLElement | null>(null);
  const location = useLocation();

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // ignore — persistence is best-effort
    }
  }, [collapsed]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    mainRef.current?.focus();
  }, [location.pathname]);

  const actions: PaletteAction[] = [];

  return (
    <div className="flex h-dvh bg-background text-foreground">
      <Sidebar collapsed={collapsed} onToggleCollapse={() => setCollapsed((v) => !v)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <StatusBar
          connection={connectionStatus}
          snapshot={snapshot}
          onOpenPalette={() => setPaletteOpen(true)}
        />
        <main
          ref={mainRef}
          tabIndex={-1}
          className="flex-1 overflow-y-auto p-6 outline-none"
        >
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} actions={actions} />
    </div>
  );
}

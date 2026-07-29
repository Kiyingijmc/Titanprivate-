import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { StatusBar } from "@/components/shell/StatusBar";
import { BottomTabs } from "@/components/shell/BottomTabs";
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

  // Responsive (design system §6.3): tablet (<1280px) forces the sidebar to the
  // icon rail; desktop restores the user's stored preference. Phone hides the
  // sidebar entirely (CSS) and shows <BottomTabs/>.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const tablet = window.matchMedia("(max-width: 1279px)");
    const apply = () => setCollapsed(tablet.matches ? true : readStoredCollapsed());
    apply();
    tablet.addEventListener("change", apply);
    return () => tablet.removeEventListener("change", apply);
  }, []);

  const actions: PaletteAction[] = [];

  return (
    <div className="flex h-dvh bg-background text-foreground">
      {/* Sidebar: hidden on phone (BottomTabs takes over there) */}
      <div className="hidden md:flex">
        <Sidebar collapsed={collapsed} onToggleCollapse={() => setCollapsed((v) => !v)} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <StatusBar
          connection={connectionStatus}
          snapshot={snapshot}
          onOpenPalette={() => setPaletteOpen((open) => !open)}
        />
        <main
          ref={mainRef}
          tabIndex={-1}
          className="flex-1 overflow-y-auto p-6 pb-20 outline-none md:pb-6"
        >
          <Outlet />
        </main>
      </div>
      {/* Phone glance nav */}
      <BottomTabs className="md:hidden" />
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} actions={actions} />
    </div>
  );
}

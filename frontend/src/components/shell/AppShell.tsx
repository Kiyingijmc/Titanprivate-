import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { StatusBar } from "@/components/shell/StatusBar";
import { BottomTabs } from "@/components/shell/BottomTabs";
import { CommandPalette } from "@/components/shell/CommandPalette";
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
import { buildCommandActions } from "@/lib/commandActions";

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
 * Owns sidebar-collapsed (persisted), palette-open (⌘K + StatusBar trigger), and pending-confirm
 * state; reads live data from ControllerContext (provided by App). ⌘K actions are built by
 * `buildCommandActions` (pause/resume/cancel run immediately; closeall/panic route through the
 * shared confirm AlertDialog below — same confirm-gate as the Controls panel).
 */
export function AppShell() {
  const { snapshot, connectionStatus, api } = useController();
  const { readOnly } = useReadOnly();
  const { run } = useMutate();
  // The user's explicit desktop preference (persisted) is kept SEPARATE from the
  // responsive override, so tablet-forced collapse never clobbers the saved pref.
  const [userCollapsed, setUserCollapsed] = useState<boolean>(readStoredCollapsed);
  const [narrow, setNarrow] = useState<boolean>(false);
  const collapsed = narrow || userCollapsed;
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<{ command: string; label: string } | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);
  const location = useLocation();

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, userCollapsed ? "1" : "0");
    } catch {
      // ignore — persistence is best-effort
    }
  }, [userCollapsed]);

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

  // Responsive (design system §6.3): tablet (<1280px) forces the icon rail via a
  // separate `narrow` flag; the persisted user preference is left untouched. Phone
  // hides the sidebar entirely (CSS) and shows <BottomTabs/>.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const tablet = window.matchMedia("(max-width: 1279px)");
    const apply = () => setNarrow(tablet.matches);
    apply();
    tablet.addEventListener("change", apply);
    return () => tablet.removeEventListener("change", apply);
  }, []);

  const actions = buildCommandActions({
    paused: snapshot?.health.paused ?? false,
    readOnly,
    run,
    api,
    requestConfirm: setPendingConfirm,
  });

  function confirmPending() {
    const pending = pendingConfirm;
    setPendingConfirm(null);
    if (!pending) return;
    run(() => api.postCommand({ command: pending.command, confirm: true }));
  }

  return (
    <div className="flex h-dvh bg-background text-foreground">
      {/* Sidebar: hidden on phone (BottomTabs takes over there) */}
      <div className="hidden md:flex">
        <Sidebar collapsed={collapsed} onToggleCollapse={() => setUserCollapsed((v) => !v)} />
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

      {/* Shared confirm-gate for destructive palette actions (closeall/panic) — mirrors
          the Controls confirm dialog; there is no unconfirmed path from the palette. */}
      <AlertDialog
        open={pendingConfirm !== null}
        onOpenChange={(open) => !open && setPendingConfirm(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{pendingConfirm?.label}?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingConfirm?.command === "panic"
                ? "This immediately closes all open positions, cancels pending orders, and pauses the bot. This cannot be undone."
                : "This immediately closes every open position. This cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmPending}>Confirm</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

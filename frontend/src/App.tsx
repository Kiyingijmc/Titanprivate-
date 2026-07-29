import { useEffect, useMemo, useState, type ReactNode } from "react";
import { RouterProvider } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { TokenGate } from "@/components/TokenGate";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { ControllerProvider } from "@/context/ControllerContext";
import { Button } from "@/components/ui/button";
import { useLiveState } from "@/lib/useLiveState";
import { createApi } from "@/lib/api";
import { router } from "@/routes/router";

// If no snapshot has arrived within this window, treat the backend as unreachable
// rather than showing "Connecting…" forever (the hook keeps retrying underneath).
const BACKEND_GRACE_MS = 10000;

function CenterScreen({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center bg-background p-6 text-sm text-muted-foreground">
      {children}
    </div>
  );
}

/** Builds the live controller connection for a confirmed token and mounts the routed shell. */
function Connected({ token, onAuthError }: { token: string; onAuthError: (message?: string) => void }) {
  const api = useMemo(() => createApi(() => token), [token]);
  const { snapshot, events, connectionStatus } = useLiveState(token, {
    onAuthError: () => onAuthError("Invalid or expired token — please reconnect."),
  });
  const [timedOut, setTimedOut] = useState(false);

  // Arm a grace timer while we have no data; Retry just re-arms it (the socket +
  // poll keep retrying independently, so a recovered backend flows in on its own).
  useEffect(() => {
    if (snapshot !== null) {
      setTimedOut(false);
      return;
    }
    const id = setTimeout(() => setTimedOut(true), BACKEND_GRACE_MS);
    return () => clearTimeout(id);
  }, [snapshot, timedOut]);

  if (snapshot === null) {
    if (timedOut || connectionStatus.status === "offline") {
      return (
        <CenterScreen>
          <div className="w-full max-w-md space-y-4 rounded-lg border border-border-strong bg-surface-1 p-6 text-left">
            <div className="flex items-center gap-2 text-warning">
              <AlertTriangle className="size-5" aria-hidden />
              <h1 className="text-base font-semibold text-foreground">Can&apos;t reach the control backend</h1>
            </div>
            <p className="text-sm text-secondary-foreground">
              No data from the Titan control API. The bot process may be down, or the API isn&apos;t
              reachable at this address. The panel keeps retrying automatically.
            </p>
            <Button onClick={() => setTimedOut(false)}>Retry</Button>
          </div>
        </CenterScreen>
      );
    }
    return <CenterScreen>Connecting…</CenterScreen>;
  }

  return (
    <ControllerProvider value={{ snapshot, events, connectionStatus, api }}>
      <ErrorBoundary>
        <RouterProvider router={router} />
      </ErrorBoundary>
    </ControllerProvider>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <TokenGate>
        {(token, onInvalid) => (
          <ReadOnlyProvider>
            <Connected token={token} onAuthError={onInvalid} />
          </ReadOnlyProvider>
        )}
      </TokenGate>
    </ErrorBoundary>
  );
}

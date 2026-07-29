import { useMemo } from "react";
import { RouterProvider } from "react-router-dom";
import { TokenGate } from "@/components/TokenGate";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { ControllerProvider } from "@/context/ControllerContext";
import { useLiveState } from "@/lib/useLiveState";
import { createApi } from "@/lib/api";
import { router } from "@/routes/router";

/** Builds the live controller connection for a confirmed token and mounts the routed shell. */
function Connected({ token }: { token: string }) {
  const api = useMemo(() => createApi(() => token), [token]);
  const { snapshot, events, connectionStatus } = useLiveState(token);

  if (connectionStatus.status === "connecting" && snapshot === null) {
    return (
      <div className="grid min-h-dvh place-items-center bg-background text-sm text-muted-foreground">
        Connecting…
      </div>
    );
  }

  return (
    <ControllerProvider value={{ snapshot, events, connectionStatus, api }}>
      <RouterProvider router={router} />
    </ControllerProvider>
  );
}

export default function App() {
  return (
    <TokenGate>
      {(token) => (
        <ReadOnlyProvider>
          <Connected token={token} />
        </ReadOnlyProvider>
      )}
    </TokenGate>
  );
}

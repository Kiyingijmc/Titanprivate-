import { createContext, useContext, type ReactNode } from "react";
import type { Snapshot, FeedEvent } from "@/lib/types";
import type { ConnectionState } from "@/lib/connection";
import type { Api } from "@/lib/api";

export interface ControllerContextValue {
  snapshot: Snapshot | null;
  events: FeedEvent[];
  connectionStatus: ConnectionState;
  api: Api;
}

const Ctx = createContext<ControllerContextValue | null>(null);

export function ControllerProvider({
  value,
  children,
}: {
  value: ControllerContextValue;
  children: ReactNode;
}) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useController() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useController outside provider");
  return v;
}

export type ConnectionStatus = "connecting" | "live" | "reconnecting" | "degraded" | "offline";
export interface ConnectionState { status: ConnectionStatus; stale: boolean; }

const DEFAULT_STALE_S = 60;

export function deriveConnection(input: {
  wsConnected: boolean; everConnected: boolean; reconnecting: boolean;
  pollOk: boolean; lastHeartbeatAgeS: number | null; staleThresholdS?: number;
}): ConnectionState {
  const stale =
    input.lastHeartbeatAgeS != null &&
    input.lastHeartbeatAgeS > (input.staleThresholdS ?? DEFAULT_STALE_S);
  let status: ConnectionStatus;
  if (input.wsConnected) status = "live";
  else if (!input.everConnected) status = "connecting";
  else if (input.pollOk) status = "degraded";     // WS down, snapshots still flowing
  else if (input.reconnecting) status = "reconnecting";
  else status = "offline";
  return { status, stale };
}

import { useEffect, useRef, useState } from "react";
import type { Snapshot, FeedEvent } from "./types";
import { deriveConnection, type ConnectionState } from "./connection";

interface Opts {
  WebSocketImpl?: typeof WebSocket;
  pollFallback?: boolean;      // default true; poll GET /api/state while disconnected
  maxEvents?: number;          // default 200
  base?: string;               // default "" (same-origin)
}

export function useLiveState(token: string | null, opts: Opts = {}) {
  const WS = opts.WebSocketImpl ?? (typeof WebSocket !== "undefined" ? WebSocket : undefined);
  const maxEvents = opts.maxEvents ?? 200;
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionState>({ status: "connecting", stale: false });
  const retry = useRef(0);
  const stopped = useRef(false);
  const connectedRef = useRef(false);
  const everConnectedRef = useRef(false);
  const pollOkRef = useRef(false);
  const reconnectingRef = useRef(false);
  const snapshotRef = useRef<Snapshot | null>(null);

  useEffect(() => {
    if (!token || !WS) return;
    stopped.current = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const refreshStatus = () => {
      setConnectionStatus(deriveConnection({
        wsConnected: connectedRef.current,
        everConnected: everConnectedRef.current,
        reconnecting: reconnectingRef.current,
        pollOk: pollOkRef.current,
        lastHeartbeatAgeS: snapshotRef.current?.health?.last_heartbeat_age_s ?? null,
      }));
    };

    const connect = () => {
      const proto = typeof location !== "undefined" && location.protocol === "https:" ? "wss" : "ws";
      const host = typeof location !== "undefined" ? location.host : "localhost";
      ws = new WS(`${opts.base ?? `${proto}://${host}`}/ws`);
      ws.onopen = () => {
        ws!.send(token); retry.current = 0;   // FIRST frame = token
        connectedRef.current = true; everConnectedRef.current = true; reconnectingRef.current = false;
        pollOkRef.current = false;   // reset: a fresh live session hasn't proven polling this cycle
        refreshStatus();
      };
      ws.onmessage = (e: MessageEvent) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "state") {
          const { type, ...snap } = msg; snapshotRef.current = snap as Snapshot;
          setSnapshot(snap as Snapshot); setConnected(true);
          refreshStatus();
        }
        else if (msg.type === "event") { const { type, ...ev } = msg; setEvents(prev => [...prev, ev as FeedEvent].slice(-maxEvents)); }
      };
      ws.onclose = () => {
        connectedRef.current = false; reconnectingRef.current = true;
        setConnected(false); refreshStatus();
        scheduleReconnect();
      };
      ws.onerror = () => { try { ws?.close(); } catch { /* ignore */ } };
    };
    const scheduleReconnect = () => {
      if (stopped.current) return;
      const delay = Math.min(1000 * 2 ** retry.current, 15000);
      retry.current += 1;
      reconnectTimer = setTimeout(connect, delay);
    };
    connect();

    // polling fallback while disconnected (same-origin GET /api/state)
    let poll: ReturnType<typeof setInterval> | undefined;
    if (opts.pollFallback !== false && typeof fetch !== "undefined") {
      poll = setInterval(async () => {
        if (connectedRef.current) return;
        try {
          const r = await fetch(`${opts.base ?? ""}/api/state`, { headers: { Authorization: `Bearer ${token}` } });
          if (r.ok) {
            const snap = await r.json();
            pollOkRef.current = true;
            snapshotRef.current = snap;
            setSnapshot(snap);
          } else {
            pollOkRef.current = false;
          }
        } catch { pollOkRef.current = false; }
        refreshStatus();
      }, 5000);
    }

    return () => {
      stopped.current = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (poll) clearInterval(poll);
      try { ws?.close(); } catch { /* ignore */ }
    };
  }, [token]);   // eslint-disable-line react-hooks/exhaustive-deps

  return { snapshot, events, connected, connectionStatus };
}

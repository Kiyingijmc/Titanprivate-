import { useEffect, useMemo, useRef, useState } from "react";
import { TokenGate } from "@/components/TokenGate";
import { ReadOnlyProvider, useReadOnly } from "@/context/ReadOnlyContext";
import { ReadOnlyBanner } from "@/components/ReadOnlyBanner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { HealthStrip } from "@/components/HealthStrip";
import { StatTiles } from "@/components/StatTiles";
import { EquitySparkline, type EquityPoint } from "@/components/EquitySparkline";
import { PositionsTable } from "@/components/PositionsTable";
import { Controls } from "@/components/Controls";
import { EventFeed } from "@/components/EventFeed";
import { StrategiesTab } from "@/components/StrategiesTab";
import { SettingsTab } from "@/components/SettingsTab";
import { useLiveState } from "@/lib/useLiveState";
import { createApi, type ApiError } from "@/lib/api";
import type { Snapshot, FeedEvent } from "@/lib/types";

const EQUITY_BUFFER_CAP = 120;

function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null && "kind" in e;
}

function Shell({ token }: { token: string }) {
  const { readOnly, setReadOnly } = useReadOnly();
  const { snapshot, events } = useLiveState(token);
  const api = useMemo(() => createApi(() => token), [token]);

  const [equityPoints, setEquityPoints] = useState<EquityPoint[]>([]);
  const tickRef = useRef(0);
  const lastEquityRef = useRef<number | null>(null);

  useEffect(() => {
    if (!snapshot) return;
    const equity = snapshot.account.equity;
    if (lastEquityRef.current === equity) return;
    lastEquityRef.current = equity;
    const t = tickRef.current;
    tickRef.current += 1;
    setEquityPoints((prev) => [...prev, { t, equity }].slice(-EQUITY_BUFFER_CAP));
  }, [snapshot]);

  function onResult(result: { readOnly?: true; error?: string }) {
    if (result.readOnly) setReadOnly(true);
  }

  async function onClosePosition(ticket: number) {
    try {
      await api.postCommand({ command: "close", ticket });
    } catch (e) {
      if (isApiError(e) && e.kind === "readOnly") {
        setReadOnly(true);
      }
      // Other failures: PositionsTable has no inline error slot; swallow here
      // rather than crash — Controls/StrategiesTab/SettingsTab surface their
      // own errors for the mutations that have one.
    }
  }

  return (
    <div className="min-h-dvh bg-background text-foreground font-sans">
      <header className="flex items-center justify-between gap-4 border-b border-border px-6 py-3">
        <h1 className="font-mono text-lg">Titan Control</h1>
        {readOnly && <ReadOnlyBanner />}
      </header>
      <main className="p-6">
        <Tabs defaultValue="cockpit">
          <TabsList>
            <TabsTrigger value="cockpit">Cockpit</TabsTrigger>
            <TabsTrigger value="strategies">Strategies</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
            <TabsTrigger value="research" disabled>
              Research
            </TabsTrigger>
            <TabsTrigger value="journal" disabled>
              Journal
            </TabsTrigger>
          </TabsList>
          <TabsContent value="cockpit">
            <Cockpit
              snapshot={snapshot}
              events={events}
              equityPoints={equityPoints}
              api={api}
              readOnly={readOnly}
              onClosePosition={onClosePosition}
              onResult={onResult}
            />
          </TabsContent>
          <TabsContent value="strategies">
            <StrategiesTab api={api} readOnly={readOnly} />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsTab api={api} readOnly={readOnly} />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

function Cockpit({
  snapshot,
  events,
  equityPoints,
  api,
  readOnly,
  onClosePosition,
  onResult,
}: {
  snapshot: Snapshot | null;
  events: FeedEvent[];
  equityPoints: EquityPoint[];
  api: ReturnType<typeof createApi>;
  readOnly: boolean;
  onClosePosition: (ticket: number) => void;
  onResult: (result: { readOnly?: true; error?: string }) => void;
}) {
  if (!snapshot) {
    return <div className="text-sm text-muted-foreground">Connecting…</div>;
  }

  const dayPnl = snapshot.account.equity - snapshot.account.balance;
  const openCount = snapshot.positions.length;

  return (
    <div className="space-y-4">
      <HealthStrip health={snapshot.health} arbiter={snapshot.arbiter} />
      <StatTiles
        account={snapshot.account}
        arbiter={snapshot.arbiter}
        dayPnl={dayPnl}
        openCount={openCount}
      />
      <EquitySparkline points={equityPoints} />
      <PositionsTable
        positions={snapshot.positions}
        onClose={onClosePosition}
        readOnly={readOnly}
      />
      <Controls
        api={api}
        paused={snapshot.health.paused}
        readOnly={readOnly}
        onResult={onResult}
      />
      <EventFeed events={events} />
    </div>
  );
}

export default function App() {
  return (
    <TokenGate>
      {(token) => (
        <ReadOnlyProvider>
          <Shell token={token} />
        </ReadOnlyProvider>
      )}
    </TokenGate>
  );
}

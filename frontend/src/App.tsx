import { TokenGate } from "@/components/TokenGate";
import { ReadOnlyProvider, useReadOnly } from "@/context/ReadOnlyContext";
import { ReadOnlyBanner } from "@/components/ReadOnlyBanner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLiveState } from "@/lib/useLiveState";
import type { Snapshot, FeedEvent } from "@/lib/types";

function Shell({ token }: { token: string }) {
  const { readOnly } = useReadOnly();
  const { snapshot, events } = useLiveState(token);

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
            <CockpitPlaceholder snapshot={snapshot} events={events} />
          </TabsContent>
          <TabsContent value="strategies">
            <Placeholder label="Strategies" />
          </TabsContent>
          <TabsContent value="settings">
            <Placeholder label="Settings" />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

function CockpitPlaceholder({
  snapshot,
  events,
}: {
  snapshot: Snapshot | null;
  events: FeedEvent[];
}) {
  return (
    <div className="text-sm text-muted-foreground">
      Cockpit — {snapshot ? "live" : "waiting for state…"} · {events.length} events
    </div>
  );
}

function Placeholder({ label }: { label: string }) {
  return <div className="text-sm text-muted-foreground">{label} — coming soon</div>;
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

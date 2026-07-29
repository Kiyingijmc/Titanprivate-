import { useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useController } from "@/context/ControllerContext";
import { EventRow } from "@/components/EventFeed";
import { Panel } from "@/components/shell/Panel";
import type { FeedEvent } from "@/lib/types";

type Filter = "ALL" | "IntentBlocked" | "IntentEmitted" | "Executions" | "State" | "GUI";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "ALL", label: "All events" },
  { value: "IntentBlocked", label: "IntentBlocked" },
  { value: "IntentEmitted", label: "IntentEmitted" },
  { value: "Executions", label: "Executions" },
  { value: "State", label: "State changes" },
  { value: "GUI", label: "GUI actions" },
];

// Above this many rows we virtualize; below it, a plain list (cheaper, and no
// layout-measurement dependency). Real event streams grow well past this.
const VIRTUALIZE_OVER = 60;

function matches(topic: string, f: Filter): boolean {
  switch (f) {
    case "ALL": return true;
    case "IntentBlocked": return topic === "IntentBlocked";
    case "IntentEmitted": return topic === "IntentEmitted";
    case "Executions": return /execution|opened|closed/i.test(topic);
    case "State": return topic === "SystemStateChanged" || topic === "StrategyActivated" || topic === "StrategySuspended";
    case "GUI": return topic === "GuiActionExecuted";
  }
}

function rowKey(ev: FeedEvent, i: number) {
  return `${ev.topic}-${ev.ts}-${i}`;
}

/** Virtualized list for large event streams (thousands of rows, constant DOM). */
function VirtualEventList({ events }: { events: FeedEvent[] }) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const rows = useVirtualizer({
    count: events.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 32,
    overscan: 12,
  });
  return (
    <div ref={parentRef} role="log" aria-live="polite" className="h-[60vh] overflow-y-auto">
      <div style={{ height: rows.getTotalSize(), position: "relative", width: "100%" }}>
        {rows.getVirtualItems().map((vi) => (
          <div
            key={rowKey(events[vi.index], vi.index)}
            style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}
            className="py-1"
          >
            <EventRow event={events[vi.index]} />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Plain list for small event counts. */
function PlainEventList({ events }: { events: FeedEvent[] }) {
  return (
    <div role="log" aria-live="polite" className="max-h-[60vh] space-y-1 overflow-y-auto">
      {events.map((ev, i) => (
        <EventRow key={rowKey(ev, i)} event={ev} />
      ))}
    </div>
  );
}

/** Activity — the full event feed: type filter + virtualized rows + blocked-rule chips. */
export default function ActivityPage() {
  const { events } = useController();
  const [filter, setFilter] = useState<Filter>("ALL");
  const filtered = useMemo<FeedEvent[]>(
    () => events.filter((e) => matches(e.topic, filter)),
    [events, filter]
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <label htmlFor="activity-filter" className="text-sm text-muted-foreground">Event type</label>
        <select
          id="activity-filter"
          aria-label="Event type"
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          className="rounded-md border border-border bg-surface-2 px-2 py-1 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
        <span className="ml-auto text-xs text-muted-foreground tabnum">{filtered.length} events</span>
      </div>

      <Panel title="Activity" status={filtered.length === 0 ? "empty" : "populated"} emptyMessage="No events yet">
        {filtered.length > VIRTUALIZE_OVER
          ? <VirtualEventList events={filtered} />
          : <PlainEventList events={filtered} />}
      </Panel>
    </div>
  );
}

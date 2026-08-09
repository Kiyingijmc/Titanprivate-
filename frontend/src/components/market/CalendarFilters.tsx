import { HORIZONS, IMPACT_LABEL, IMPACT_ORDER, type CalendarFilterState, type Impact }
  from "@/lib/newsCalendar";
import { cn } from "@/lib/utils";

function Toggle({ label, pressed, onClick }:
                { label: string; pressed: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        pressed
          ? "border-accent bg-accent/20 text-foreground"
          : "border-border bg-surface-2 text-muted-foreground hover:text-foreground")}
    >
      {label}
    </button>
  );
}

export function CalendarFilters({ value, onChange }:
    { value: CalendarFilterState; onChange: (next: CalendarFilterState) => void }) {
  const toggleImpact = (impact: Impact) => {
    const has = value.impacts.includes(impact);
    // Rebuilt from IMPACT_ORDER rather than push/splice, so the array order is
    // canonical no matter which sequence the operator clicked them in.
    const next = IMPACT_ORDER.filter(i =>
      i === impact ? !has : value.impacts.includes(i));
    onChange({ ...value, impacts: next });
  };

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5 border-b border-border bg-surface-1 px-4 py-2.5">
      {IMPACT_ORDER.map(impact => (
        <Toggle key={impact} label={IMPACT_LABEL[impact]}
                pressed={value.impacts.includes(impact)}
                onClick={() => toggleImpact(impact)} />
      ))}
      <span className="w-2" aria-hidden />
      <Toggle label="Affects my book" pressed={value.affectsMyBookOnly}
              onClick={() => onChange({ ...value, affectsMyBookOnly: !value.affectsMyBookOnly })} />
      <span className="flex-1" aria-hidden />
      <div className="flex overflow-hidden rounded-md border border-border">
        {HORIZONS.map(h => (
          <button
            key={h.id}
            type="button"
            aria-pressed={value.horizon === h.id}
            onClick={() => onChange({ ...value, horizon: h.id })}
            className={cn(
              "border-r border-border px-2.5 py-0.5 text-xs last:border-r-0 transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              value.horizon === h.id
                ? "bg-accent/20 text-foreground"
                : "text-muted-foreground hover:text-foreground")}
          >
            {h.label}
          </button>
        ))}
      </div>
    </div>
  );
}

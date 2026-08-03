export interface LegendEntry {
  key: string;
  label: string;
  /** The same colour string the series is drawn with, so a token retune moves
   *  the swatch and the series together. */
  swatch: string;
  dashed?: boolean;
}

/**
 * Static key for one chart pane. Deliberately NOT interactive: a click-to-hide
 * series is hidden state that every screenshot and bug report then has to
 * account for, and nothing asked for it.
 */
export function EquityLegend({ entries }: { entries: LegendEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div
      data-testid="equity-legend"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 pt-1 text-[11px] text-muted-foreground"
    >
      {entries.map((e) => (
        <span key={e.key} className="inline-flex items-center gap-1.5">
          <span
            data-testid="legend-swatch"
            aria-hidden
            className="inline-block h-0.5 w-3 rounded-full"
            style={
              e.dashed
                ? { backgroundImage: `repeating-linear-gradient(90deg, ${e.swatch} 0 4px, transparent 4px 7px)` }
                : { backgroundColor: e.swatch }
            }
          />
          {e.label}
        </span>
      ))}
    </div>
  );
}

import { Palette } from "lucide-react";
import { useAccent } from "@/lib/useAccent";
import { cn } from "@/lib/utils";

/**
 * Compact signature-accent switcher for the StatusBar: a live swatch (reads the
 * current --accent so it recolors itself instantly) + a palette glyph. One click
 * flips violet ↔ electric blue; the choice persists via useAccent.
 */
export function AccentToggle() {
  const { accent, toggle } = useAccent();
  const label = accent === "violet" ? "Violet" : "Electric Blue";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Accent color: ${label} — click to switch`}
      title={`Accent: ${label} — click to switch`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-muted-foreground",
        "hover:bg-surface-2 hover:text-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      <span
        className="size-3 rounded-full ring-1 ring-inset ring-white/20"
        style={{ background: "hsl(var(--accent))" }}
        aria-hidden
      />
      <Palette className="size-4" aria-hidden />
    </button>
  );
}

import { Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Opens a panel's maximized (75%) view.
 *
 * Presentational only — the parent owns the open/closed state, which is what
 * makes "only one panel maximized at a time" structural rather than a rule to
 * enforce. Carries NO data-testid: two of these coexist on the Overview page,
 * and a shared testid would break the single-match queries the suite relies on.
 */
export function MaximizeButton({ title, onClick }: { title: string; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={onClick}
      aria-label={`Maximize ${title}`}
    >
      <Maximize2 className="size-4" aria-hidden />
    </Button>
  );
}

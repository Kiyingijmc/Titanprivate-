import { Lock } from "lucide-react";

export function ReadOnlyBanner() {
  return (
    <div className="flex items-center gap-2 bg-warning/15 text-warning border border-warning/30 rounded-md px-3 py-1.5 text-sm">
      <Lock className="size-4" aria-hidden /> Read-only mode — controls disabled
    </div>
  );
}

import { useState } from "react";
import { Pause, Play, XCircle, Ban, OctagonAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { Api, ApiError } from "@/lib/api";

type DestructiveCommand = "closeall" | "panic";

function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null && "kind" in e;
}

/**
 * Button group per design-system §6: pause/resume/cancel call the api directly;
 * closeall/panic are destructive (loss-red, visually separated) and require an
 * explicit AlertDialog confirm before POSTing {command, confirm:true} — mirrors
 * the backend confirm-gate (src/ops/web/commands.py _DESTRUCTIVE).
 */
export function Controls({
  api,
  paused,
  readOnly,
  onResult,
}: {
  api: Api;
  paused: boolean;
  readOnly: boolean;
  onResult: (result: { readOnly: true }) => void;
}) {
  const [pending, setPending] = useState<DestructiveCommand | null>(null);

  async function run(command: string, extra: Record<string, unknown> = {}) {
    try {
      await api.postCommand({ command, ...extra });
    } catch (e) {
      if (isApiError(e) && e.kind === "readOnly") {
        onResult({ readOnly: true });
      }
    }
  }

  async function confirmDestructive() {
    const command = pending;
    setPending(null);
    if (!command) return;
    await run(command, { confirm: true });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-2">
        {paused ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={readOnly}
            onClick={() => run("resume")}
          >
            <Play aria-hidden /> Resume
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={readOnly}
            onClick={() => run("pause")}
          >
            <Pause aria-hidden /> Pause
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={readOnly}
          onClick={() => run("cancel")}
        >
          <XCircle aria-hidden /> Cancel
        </Button>
      </div>

      <div className="ml-2 flex items-center gap-2 border-l border-border pl-2">
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={readOnly}
          onClick={() => setPending("closeall")}
        >
          <Ban aria-hidden /> Close All
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={readOnly}
          onClick={() => setPending("panic")}
        >
          <OctagonAlert aria-hidden /> Panic
        </Button>
      </div>

      <AlertDialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pending === "panic" ? "Panic — halt everything?" : "Close all positions?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pending === "panic"
                ? "This immediately closes all open positions, cancels pending orders, and pauses the bot. This cannot be undone."
                : "This immediately closes every open position. This cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDestructive}>Confirm</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

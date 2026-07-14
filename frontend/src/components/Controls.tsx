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
  onResult: (result: { readOnly?: true; error?: string }) => void;
}) {
  const [pending, setPending] = useState<DestructiveCommand | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(command: string, extra: Record<string, unknown> = {}) {
    setError(null);
    try {
      await api.postCommand({ command, ...extra });
    } catch (e) {
      // A failed command — especially a destructive one — must never look like
      // success. Read-only routes to the read-only banner; every other failure
      // (network, 5xx, 429 throttle, 422) surfaces a visible operator alert.
      if (isApiError(e) && e.kind === "readOnly") {
        onResult({ readOnly: true });
        return;
      }
      const detail = isApiError(e)
        ? e.kind === "throttled"
          ? "Rate limited — wait and retry"
          : e.detail || "Command failed"
        : "Command failed — check the connection";
      setError(`${command}: ${detail}`);
      onResult({ error: detail });
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

      {error && (
        <div role="alert" className="flex items-center gap-2 text-sm text-loss">
          <OctagonAlert className="size-4" aria-hidden /> {error}
        </div>
      )}

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

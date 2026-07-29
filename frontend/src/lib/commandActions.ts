import type { PaletteAction } from "@/components/shell/CommandPalette";
import type { Api } from "@/lib/api";

export interface BuildCommandActionsOpts {
  paused: boolean;
  readOnly: boolean;
  /** Injected `useMutate().run` — routes 403 to read-only, surfaces other failures. */
  run: (fn: () => Promise<unknown>) => void;
  api: Api;
  /** Opens the shared confirm AlertDialog owned by AppShell; destructive actions never call the api directly. */
  requestConfirm: (action: { command: string; label: string }) => void;
}

/**
 * Pure builder for the ⌘K palette's "Actions" group (design-system §4.3 / Plan 2 Task 7).
 * Mirrors the Controls confirm-gate (src/components/Controls.tsx): pause/resume/cancel run
 * immediately through `run`; closeall/panic are destructive and only ever open the shared
 * confirm dialog via `requestConfirm` — there is no second, unconfirmed path to the backend.
 * Every action is disabled while `readOnly` is true.
 */
export function buildCommandActions({
  paused,
  readOnly,
  run,
  api,
  requestConfirm,
}: BuildCommandActionsOpts): PaletteAction[] {
  return [
    paused
      ? {
          id: "resume",
          label: "Resume",
          disabled: readOnly,
          run: () => run(() => api.postCommand({ command: "resume" })),
        }
      : {
          id: "pause",
          label: "Pause",
          disabled: readOnly,
          run: () => run(() => api.postCommand({ command: "pause" })),
        },
    {
      id: "cancel",
      label: "Cancel pending",
      disabled: readOnly,
      run: () => run(() => api.postCommand({ command: "cancel" })),
    },
    {
      id: "closeall",
      label: "Close all positions",
      destructive: true,
      disabled: readOnly,
      run: () => requestConfirm({ command: "closeall", label: "Close all positions" }),
    },
    {
      id: "panic",
      label: "Panic — halt everything",
      destructive: true,
      disabled: readOnly,
      run: () => requestConfirm({ command: "panic", label: "Panic — halt everything" }),
    },
  ];
}

import * as React from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * A panel's maximized view: 75% of the viewport from `md` up, near-full below
 * it (75% of a phone screen is unusable).
 *
 * `max-w-none` is REQUIRED. The stock DialogContent carries `max-w-lg`, which
 * silently caps the dialog at 32rem no matter which width class is applied.
 * `flex` likewise overrides DialogContent's stock `grid` — `cn` runs
 * tailwind-merge, so the later display utility wins.
 *
 * The body is `flex-1 min-h-0` so children can FILL it. Without `min-h-0` a
 * flex child refuses to shrink below its content height, and the chart
 * overflows the dialog instead of fitting inside it.
 *
 * Escape, click-outside, focus trap and body scroll lock all come from Radix.
 * Open/close motion comes from the `[data-titan-dialog]` keyframes already in
 * index.css, so reduced-motion is handled globally.
 *
 * FOCUS RESTORATION IS MANUAL, not Radix's default. Radix's own
 * onCloseAutoFocus restores focus to `Dialog.Trigger` — but the maximize
 * button that opens this dialog lives inside a separate `Panel`/
 * `MaximizeButton`, never wrapped in a literal `<Dialog.Trigger>` (the parent
 * owns `open` as external state), so Radix has no trigger ref to return to
 * and focus would otherwise fall back to `<body>`.
 *
 * The snapshot is taken in `onOpenAutoFocus`, NOT during render: writing to a
 * ref during render violates React's render-purity rule (a render started
 * then discarded before commit — e.g. under a concurrent-mode interruption —
 * could mark the ref "seen" without ever committing, silently skipping the
 * next real capture). `onOpenAutoFocus` is an event handler Radix's
 * `FocusScope` fires synchronously on mount, BEFORE it moves focus into the
 * dialog content (verified against `@radix-ui/react-focus-scope`'s source:
 * it reads `document.activeElement` into `previouslyFocusedElement`, THEN
 * dispatches the mount-autofocus event, and only afterward — gated on the
 * event not being defaultPrevented — calls `focusFirst` to steal focus into
 * the content). So `document.activeElement` inside this handler is still the
 * real trigger — USUALLY. Some callers (the news dialog) unmount their
 * trigger's whole subtree while the dialog is open, so the button's DOM node
 * can be destroyed before this snapshot is even read back on close (a
 * passive-effect vs. mutation-phase ordering issue, not something this
 * component controls). So the snapshot alone is not trustworthy at close
 * time: `onCloseAutoFocus` revalidates it and falls back in this order:
 *   1. the snapshot, if it is still a connected, non-`<body>` element;
 *   2. otherwise the trigger re-located by its accessible name (`triggerLabel`,
 *      which MUST match the `MaximizeButton`'s `aria-label`) — this is what
 *      saves the news dialog, whose trigger remounts under a NEW DOM node
 *      once `NewsPanel` comes back after the placeholder branch;
 *   3. otherwise `preventDefault()` is NOT called at all, so Radix's own
 *      (trigger-less, falls back to `<body>`) restoration proceeds instead of
 *      this component silently focusing nothing.
 */
export function MaximizedDialog({
  open,
  onOpenChange,
  title,
  children,
  triggerLabel,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
  /** Accessible name of the button that opens this dialog (its `aria-label`,
   *  e.g. `Maximize ${title}`). Used to relocate the trigger on close when the
   *  original snapshot is gone — see the focus-restoration note above. */
  triggerLabel?: string;
}) {
  const triggerRef = React.useRef<HTMLElement | null>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex max-w-none flex-col gap-3",
          "h-[85vh] w-[95vw] md:h-[75vh] md:w-[75vw]"
        )}
        aria-describedby={undefined}
        onOpenAutoFocus={() => {
          triggerRef.current = document.activeElement as HTMLElement | null;
        }}
        onCloseAutoFocus={(event) => {
          const snapshot = triggerRef.current;
          if (isReturnable(snapshot)) {
            event.preventDefault();
            snapshot.focus();
            return;
          }
          const relocated = triggerLabel
            ? document.querySelector<HTMLElement>(`[aria-label="${triggerLabel}"]`)
            : null;
          if (isReturnable(relocated)) {
            event.preventDefault();
            relocated.focus();
            return;
          }
          // No valid target on either path — let Radix's default restoration
          // run rather than preventDefault-ing into focusing nothing.
        }}
      >
        <DialogTitle>{title}</DialogTitle>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </DialogContent>
    </Dialog>
  );
}

/** A snapshot/relocated candidate is only worth restoring focus to if it is
 *  still attached to the document and isn't the `<body>` fallback that
 *  `document.activeElement` reports when nothing was actually focused. */
function isReturnable(el: HTMLElement | null): el is HTMLElement {
  return el !== null && el !== document.body && document.contains(el);
}

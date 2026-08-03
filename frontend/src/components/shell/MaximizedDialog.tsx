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
 * real trigger. `onCloseAutoFocus` then `preventDefault()`s Radix's own
 * (trigger-less) restoration and focuses that snapshot instead.
 */
export function MaximizedDialog({
  open,
  onOpenChange,
  title,
  children,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  const triggerRef = React.useRef<HTMLElement | null>(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex max-w-none flex-col gap-3",
          "h-[85vh] w-[95vw] md:h-[75vh] md:w-[75vw]",
          className
        )}
        onOpenAutoFocus={() => {
          triggerRef.current = document.activeElement as HTMLElement | null;
        }}
        onCloseAutoFocus={(event) => {
          if (triggerRef.current) {
            event.preventDefault();
            triggerRef.current.focus();
          }
        }}
      >
        <DialogTitle>{title}</DialogTitle>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </DialogContent>
    </Dialog>
  );
}

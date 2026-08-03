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
 * and focus would otherwise fall back to `<body>`. `triggerRef` snapshots
 * `document.activeElement` synchronously during render the instant `open`
 * flips true — before Radix's FocusScope mounts and moves focus into the
 * dialog — so it captures the real trigger, not whatever the dialog
 * refocused. `onCloseAutoFocus` then `preventDefault()`s Radix's own
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
  const wasOpenRef = React.useRef(false);
  const triggerRef = React.useRef<HTMLElement | null>(null);
  if (open && !wasOpenRef.current) {
    triggerRef.current = document.activeElement as HTMLElement | null;
  }
  wasOpenRef.current = open;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex max-w-none flex-col gap-3",
          "h-[85vh] w-[95vw] md:h-[75vh] md:w-[75vw]",
          className
        )}
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

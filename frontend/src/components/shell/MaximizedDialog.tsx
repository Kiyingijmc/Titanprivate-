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
 * Escape, click-outside, focus trap, focus restoration and body scroll lock all
 * come from Radix. Open/close motion comes from the `[data-titan-dialog]`
 * keyframes already in index.css, so reduced-motion is handled globally.
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex max-w-none flex-col gap-3",
          "h-[85vh] w-[95vw] md:h-[75vh] md:w-[75vw]",
          className
        )}
      >
        <DialogTitle>{title}</DialogTitle>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </DialogContent>
    </Dialog>
  );
}

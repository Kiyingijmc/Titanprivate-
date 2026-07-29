import { cn } from "@/lib/utils";

/**
 * Titan brand mark + wordmark. The mark is the "Bracket" concept from the brand
 * board (docs/branding/brand-board) — a corner-bracket pair enclosing a center
 * node, in currentColor so it inherits the accent. The wordmark is Instrument Sans.
 */
export function Logo({ variant = "full", className }: { variant?: "full" | "mark"; className?: string }) {
  const mark = (
    <svg
      viewBox="0 0 32 32"
      role="img"
      aria-label="Titan"
      className={cn("size-6", variant === "mark" ? className : undefined)}
      fill="currentColor"
    >
      <path d="M4 13V4h9v3.6H7.6V13z" />
      <path d="M28 19v9h-9v-3.6h5.4V19z" />
      <path d="M13.8 13.8h4.4v4.4h-4.4z" />
    </svg>
  );
  if (variant === "mark") return mark;
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span className="text-accent">{mark}</span>
      <span className="font-sans text-lg font-semibold tracking-tight text-foreground">Titan</span>
    </span>
  );
}

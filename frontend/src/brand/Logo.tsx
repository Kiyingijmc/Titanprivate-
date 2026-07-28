export function Logo({ variant = "full", className }: { variant?: "full" | "mark"; className?: string }) {
  const mark = (
    <svg viewBox="0 0 24 24" aria-hidden className={className} fill="none" stroke="currentColor" strokeWidth={2}>
      {/* placeholder geometric mark — replaced by the brand board's SVG */}
      <path d="M4 5h16M12 5v14M7 19h10" strokeLinecap="round" />
    </svg>
  );
  if (variant === "mark") return mark;
  return (
    <span className={"inline-flex items-center gap-2 font-mono font-semibold tracking-tight " + (className ?? "")}>
      <span className="text-accent">{mark}</span> Titan
    </span>
  );
}

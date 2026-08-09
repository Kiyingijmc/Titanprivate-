import { IMPACT_LABEL, type Impact } from "@/lib/newsCalendar";
import { cn } from "@/lib/utils";

/** Consumer of the --impact-* tokens A2 left with no consumer.
 *
 *  --impact-high (hue 10) sits ~12deg from --loss (hue 358) — deliberately,
 *  both are red by convention. So "high-impact release" and "losing money"
 *  could be confused at a glance and would be indistinguishable to a
 *  red-green colour-blind operator. The LABEL is the carrier; the colour is
 *  redundant. Never render this chip without its text. */
const TEXT: Record<Impact, string> = {
  HIGH: "text-impact-high", MEDIUM: "text-impact-medium", LOW: "text-impact-low",
};
const DOT: Record<Impact, string> = {
  HIGH: "bg-impact-high", MEDIUM: "bg-impact-medium", LOW: "bg-impact-low",
};

export function ImpactChip({ impact, className }: { impact: Impact; className?: string }) {
  return (
    <span
      data-impact={impact}
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-[10px] font-bold uppercase tracking-wide",
                    TEXT[impact], className)}
    >
      <span className={cn("size-1.5 rounded-[2px]", DOT[impact])} aria-hidden />
      {IMPACT_LABEL[impact]}
    </span>
  );
}

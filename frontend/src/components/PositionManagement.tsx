import { Activity, ArrowUpRight, ShieldCheck, ShieldAlert, Timer } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { Position, PositionManagement as Management } from "@/lib/types";
import { price, signedPnl, pnlToneClass } from "@/lib/format";
import { cn } from "@/lib/utils";

export function managementLabel(m?: Management | null) {
  return m?.mode === "m15_structure_v1" ? "M15 structure" : m?.mode === "legacy" ? "Legacy ratchet" : "Not assigned";
}

const volume = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 8 });
const value = (n?: number | null) => n == null || !Number.isFinite(n) ? "—" : price(n);

export function PositionSummary({ positions, loading, stale }: { positions: Position[]; loading: boolean; stale: boolean }) {
  const pnl = signedPnl(positions.reduce((sum, p) => sum + p.pnl, 0));
  const stops = positions.filter(p => p.sl > 0).length;
  const unknown = positions.filter(p => !p.management).length;
  const pending = positions.filter(p => p.management?.pending).length;
  const metrics = [
    { label: "Open positions", value: String(positions.length), note: `${new Set(positions.map(p => p.symbol)).size} instruments`, Icon: Activity, tone: "text-foreground" },
    { label: "Floating P&L", value: pnl.text, note: "Account currency · open trades", Icon: ArrowUpRight, tone: pnlToneClass(pnl.tone) },
    { label: "Broker stops", value: `${stops} / ${positions.length}`, note: stops < positions.length ? `${positions.length - stops} without a stop` : "Stop-loss reported by broker", Icon: stops < positions.length ? ShieldAlert : ShieldCheck, tone: stops < positions.length ? "text-warning" : "text-foreground" },
    { label: "Awaiting confirmation", value: unknown ? (unknown === positions.length ? "—" : `${pending} known`) : String(pending), note: unknown ? `${unknown} with unavailable management status` : "Management requests in progress", Icon: Timer, tone: pending ? "text-warning" : "text-foreground" },
  ];
  return <section aria-label="Position summary" className="grid grid-cols-2 gap-3 xl:grid-cols-4">
    {metrics.map(({ label, value: text, note, Icon, tone }) => <div key={label} className="min-w-0 rounded-lg border border-border bg-surface-1 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-2 text-xs text-secondary-foreground"><span>{label}</span><Icon className="size-4 shrink-0" aria-hidden /></div>
      <p className={cn("mt-3 break-words font-mono text-2xl font-medium tracking-tight tabnum", tone)}>{loading ? "—" : text}</p>
      <p className="mt-2 text-xs text-secondary-foreground">{loading ? "Waiting for the broker" : stale ? "Last received snapshot" : note}</p>
    </div>)}
  </section>;
}

export function PositionDetails({ position: p, stale = false, compact = false }: { position: Position; stale?: boolean; compact?: boolean }) {
  const m = p.management;
  const progress = m?.progress_pct;
  const knownProgress = progress != null && Number.isFinite(progress);
  const width = knownProgress ? Math.min(100, Math.max(0, progress)) : 0;
  const pnl = signedPnl(p.pnl);
  return <Dialog>
    <DialogTrigger asChild>
      <button type="button" aria-label={compact ? `Trade details for ${p.symbol} ${p.ticket}` : `Inspect position ${p.ticket}`} className={cn("inline-flex min-h-11 items-center gap-2 rounded-md text-left hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", compact ? "font-semibold text-foreground" : "px-2 text-xs text-secondary-foreground")}>
        {compact ? <span>{p.symbol}</span> : <>
        <span className={cn("size-1.5 shrink-0 rounded-full", m?.pending ? "bg-warning" : m?.mode === "m15_structure_v1" ? "bg-accent" : "bg-muted-foreground")} aria-hidden />
        <span>{m?.pending ? "Awaiting broker" : managementLabel(m)}<span className="block text-[11px] text-secondary-foreground">View trade details</span></span>
        <ArrowUpRight className="size-3.5 shrink-0" aria-hidden />
        </>}
      </button>
    </DialogTrigger>
    <DialogContent className="max-h-[90dvh] w-[calc(100%-2rem)] max-w-xl overflow-y-auto rounded-xl p-5 sm:p-6">
      <DialogHeader>
        <DialogTitle className="pr-6 text-left font-sans text-xl">{p.symbol} <span className="text-sm font-normal text-secondary-foreground">{p.side} · #{p.ticket}</span></DialogTitle>
        <DialogDescription className="text-left">{p.strategy || "Strategy unavailable"} · {managementLabel(m)}</DialogDescription>
      </DialogHeader>
      {stale && <p role="status" className="rounded-md bg-warning/10 p-3 text-sm text-warning">Data may be delayed. These are the last received values.</p>}
      <div className="flex items-end justify-between rounded-lg bg-surface-2/60 p-4">
        <div><p className="text-xs text-secondary-foreground">Floating P&L · account currency</p><p className={cn("mt-1 font-mono text-2xl tabnum", pnlToneClass(pnl.tone))}>{pnl.text}</p></div>
        <div className="text-right"><p className="text-xs text-secondary-foreground">Remaining volume</p><p className="mt-1 font-mono tabnum">{volume(p.lots)} lots</p></div>
      </div>
      <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
        {[["Entry", value(p.entry)], ["Broker stop-loss", p.sl > 0 ? value(p.sl) : "No stop"], ["Broker take-profit", p.tp > 0 ? value(p.tp) : "No fixed TP"], ["Original target", value(m?.original_tp)], ["Exit stage", m ? (m.confirmed_level >= 3 ? "Runner stage" : m.confirmed_level >= 2 ? "First stage complete" : m.confirmed_level === 1 ? "Break-even stage" : "Initial stage") : "—"], ["Partial stage confirmed", m ? String(m.confirmed_partial_stage) : "—"]].map(([label, text]) => <div key={label}><dt className="text-xs text-secondary-foreground">{label}</dt><dd className="mt-1 font-mono tabnum">{text}</dd></div>)}
      </dl>
      <section className="rounded-lg border border-border p-4" aria-label="Target progress">
        <div className="flex justify-between gap-3 text-sm"><h3 className="font-medium">Progress to original target</h3><span className="font-mono tabnum">{knownProgress ? `${progress.toFixed(1)}%` : "Unavailable"}</span></div>
        <div className="relative mt-3 h-2 overflow-hidden rounded-full bg-surface-2" role={knownProgress ? "progressbar" : undefined} aria-label="Progress to original target" aria-valuemin={0} aria-valuemax={100} aria-valuenow={knownProgress ? width : undefined} aria-valuetext={knownProgress ? `${progress.toFixed(1)}% of original target distance` : undefined}>
          <div className="h-full rounded-full bg-accent" style={{ width: `${width}%` }} />
        </div>
        <p className="mt-2 text-xs leading-relaxed text-secondary-foreground">{m?.first_partial_pct != null ? `First partial becomes eligible at ${m.first_partial_pct}% of the original target distance.` : "Management thresholds are not available for this trade."} Progress uses the executable side of the quote.</p>
      </section>
      {m?.pending && <section className="rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm" aria-label="Pending management request">
        <h3 className="flex items-center gap-2 font-medium text-warning"><Timer className="size-4" aria-hidden /> Awaiting broker confirmation</h3>
        <p className="mt-2 text-secondary-foreground">Requested changes are not confirmed executions.</p>
        <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
          {m.target_volume != null && <div><dt>Requested remaining volume</dt><dd className="mt-1 font-mono">{volume(m.target_volume)} lots</dd></div>}
          {m.requested_sl != null && <div><dt>Requested stop-loss</dt><dd className="mt-1 font-mono">{value(m.requested_sl)}</dd></div>}
          {m.requested_tp != null && <div><dt>Requested take-profit</dt><dd className="mt-1 font-mono">{m.requested_tp === 0 ? "Remove fixed TP" : value(m.requested_tp)}</dd></div>}
        </dl>
      </section>}
      {m?.mode === "m15_structure_v1" && <p className="text-xs leading-relaxed text-secondary-foreground">{m.context_ready ? "M15 context available." : "Waiting for valid M15 context; existing broker protection remains in place."} Structural trailing uses confirmed pullback swings after the first stage confirms. Partial size varies with volatility and trend strength.</p>}
      {!m && <p className="text-xs text-secondary-foreground">Management information is unavailable. Broker prices and volume above remain visible.</p>}
    </DialogContent>
  </Dialog>;
}

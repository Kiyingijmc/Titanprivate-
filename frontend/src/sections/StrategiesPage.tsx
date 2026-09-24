import { StrategiesTab } from "@/components/StrategiesTab";
import { useController } from "@/context/ControllerContext";
import { useReadOnly } from "@/context/ReadOnlyContext";

/** Registry data and refresh status have one owner: StrategiesTab. */
export default function StrategiesPage() {
  const { api } = useController();
  const { readOnly, setReadOnly } = useReadOnly();
  return <div className="grid min-w-0 gap-5">
    <header><p className="text-xs font-medium uppercase tracking-[0.16em] text-accent">Strategy workspace</p><h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Your strategy library</h1><p className="mt-2 text-sm text-secondary-foreground">Review runtime states, compare classifications, and manage strategy availability.</p></header>
    <StrategiesTab api={api} readOnly={readOnly} onReadOnly={() => setReadOnly(true)} />
  </div>;
}

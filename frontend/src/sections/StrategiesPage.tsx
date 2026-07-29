import { useCallback, useEffect, useState } from "react";
import { Panel, type PanelStatus } from "@/components/shell/Panel";
import { StrategiesTab } from "@/components/StrategiesTab";
import { useController } from "@/context/ControllerContext";
import { useReadOnly } from "@/context/ReadOnlyContext";

/**
 * Strategies section (design-system §6): StrategiesTab owns the registry
 * table's own load/mutate lifecycle (it keeps its last-good rows rather than
 * crash on a failed load), so it can't surface the Panel's loading/error/retry
 * affordance on its own. This page runs its own getRegistry probe purely to
 * drive the wrapping Panel's status; StrategiesTab still fetches and renders
 * the table itself once the Panel is populated. A registryAction 403 (typed
 * via onReadOnly) flips the shared read-only flag, disabling further
 * enable/disable/promote across the app.
 */
export default function StrategiesPage() {
  const { api } = useController();
  const { readOnly, setReadOnly } = useReadOnly();
  const [status, setStatus] = useState<PanelStatus>("loading");

  const load = useCallback(() => {
    setStatus("loading");
    api
      .getRegistry()
      .then(() => setStatus("populated"))
      .catch(() => setStatus("error"));
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Panel status={status} title="Strategies" onRetry={load}>
      <StrategiesTab api={api} readOnly={readOnly} onReadOnly={() => setReadOnly(true)} />
    </Panel>
  );
}

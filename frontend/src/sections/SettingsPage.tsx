import { useState } from "react";
import { Panel } from "@/components/shell/Panel";
import { Input } from "@/components/ui/input";
import { SettingsTab } from "@/components/SettingsTab";
import { useController } from "@/context/ControllerContext";
import { useReadOnly } from "@/context/ReadOnlyContext";

/**
 * Settings section (design-system §5): a search box filtering rows by key,
 * grouped by domain (the dotted-key prefix). All source/tier badges, edit +
 * inline-422 behavior live in SettingsTab (single source of truth) — this
 * page only supplies the search string and the groupByDomain layout, and
 * owns no fetch of its own (SettingsTab loads via api.getSettings).
 */
export default function SettingsPage() {
  const { api } = useController();
  const { readOnly } = useReadOnly();
  const [search, setSearch] = useState("");

  return (
    <Panel status="populated" title="Settings">
      <div className="grid gap-4">
        <Input
          aria-label="Search settings"
          placeholder="Search settings by key…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <SettingsTab api={api} readOnly={readOnly} filter={search} groupByDomain />
      </div>
    </Panel>
  );
}

"""StrategyRegistry: manifest-driven strategy lifecycle (Plan 04, Trading OS).

Lifecycle FSM: REGISTERED -> LOADED -> ACTIVE <-> SUSPENDED.

- load_all() imports + instantiates every manifest's class, validates
  FeatureBus `requires` (if a bus is given), and raises RegistryError
  fail-fast on any failure -- this runs at boot, before trading starts.
- activate_eligible() promotes LOADED strategies with status demo/live
  (and not explicitly disabled via params) to ACTIVE, publishing
  StrategyActivated on the tape. research-status strategies stay LOADED.
- enable()/disable() are the operator-facing (Telegram) surface: they
  never raise -- unknown ids and illegal transitions return a
  human-readable message and leave state untouched.
"""
from __future__ import annotations

import importlib

from src.core.events import StrategyActivated, StrategySuspended

_ACTIVATABLE_STATUSES = ("demo", "live")


class RegistryError(ValueError):
    """Raised by load_all() on import/instantiation failure or unresolved requires."""


class StrategyRegistry:
    def __init__(self, manifests, params_by_id, logger, publish=None, feature_bus=None):
        self._manifests = list(manifests)
        self._by_id = {m.id: m for m in self._manifests}
        self._params_by_id = params_by_id or {}
        self._logger = logger
        self._publish = publish
        self._feature_bus = feature_bus
        self._state = {m.id: "REGISTERED" for m in self._manifests}
        self._instances = {}

    def _emit(self, event) -> None:
        if self._publish is not None:
            self._publish(event)

    def load_all(self) -> None:
        for manifest in self._manifests:
            module_name, class_name = manifest.class_path.split(":")
            try:
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
            except Exception as exc:
                raise RegistryError(
                    f"{manifest.id}: failed to import class '{manifest.class_path}': {exc}"
                ) from exc

            params = self._params_by_id.get(manifest.id, {})
            try:
                instance = cls(params, self._logger)
            except Exception as exc:
                raise RegistryError(
                    f"{manifest.id}: failed to instantiate '{manifest.class_path}': {exc}"
                ) from exc

            if self._feature_bus is not None:
                available = getattr(self._feature_bus, "_registry", {})
                missing = [r for r in manifest.requires if r not in available]
                if missing:
                    raise RegistryError(
                        f"{manifest.id}: unresolved FeatureBus requirement(s): {missing}"
                    )

            self._instances[manifest.id] = instance
            # Tag the live instance so the controller's HTF-bias filter can
            # honor the manifest without a registry lookup on the hot path
            # (and so the registry-less parity/research harnesses default
            # to honoring via getattr(..., True)).
            instance.honors_htf_bias = manifest.honors_htf_bias
            self._state[manifest.id] = "LOADED"

        names_seen = {}
        for manifest in self._manifests:
            name = getattr(self._instances[manifest.id], "name", None)
            if name in names_seen:
                raise RegistryError(
                    f"duplicate instance name '{name}': manifests "
                    f"'{names_seen[name]}' and '{manifest.id}' both resolve to it"
                )
            names_seen[name] = manifest.id

    def activate_eligible(self) -> None:
        for manifest in self._manifests:
            if self._state.get(manifest.id) != "LOADED":
                continue
            if manifest.status not in _ACTIVATABLE_STATUSES:
                continue
            params = self._params_by_id.get(manifest.id, {})
            if params.get("enabled", True) is False:
                continue
            self._state[manifest.id] = "ACTIVE"
            self._emit(
                StrategyActivated(
                    strategy_id=manifest.id,
                    version=manifest.version,
                    family=manifest.family,
                    timeframe=manifest.timeframe,
                )
            )

    def enable(self, strategy_id, allow_research=False) -> str:
        manifest = self._by_id.get(strategy_id)
        if manifest is None:
            return f"Unknown strategy '{strategy_id}'."
        if manifest.status == "research" and not allow_research:
            return (
                f"⛔ '{strategy_id}' is research-status (ungated). "
                f"Use `/enable {strategy_id} confirm` to override."
            )
        state = self._state.get(strategy_id)
        if state not in ("LOADED", "SUSPENDED"):
            return f"Cannot enable '{strategy_id}': illegal transition from {state}."
        self._state[strategy_id] = "ACTIVE"
        self._emit(
            StrategyActivated(
                strategy_id=manifest.id,
                version=manifest.version,
                family=manifest.family,
                timeframe=manifest.timeframe,
            )
        )
        return f"Strategy '{strategy_id}' enabled (now ACTIVE)."

    def disable(self, strategy_id, reason="operator") -> str:
        manifest = self._by_id.get(strategy_id)
        if manifest is None:
            return f"Unknown strategy '{strategy_id}'."
        state = self._state.get(strategy_id)
        if state != "ACTIVE":
            return f"Cannot disable '{strategy_id}': illegal transition from {state}."
        self._state[strategy_id] = "SUSPENDED"
        self._emit(
            StrategySuspended(strategy_id=manifest.id, version=manifest.version, reason=reason)
        )
        return f"Strategy '{strategy_id}' disabled (now SUSPENDED): {reason}."

    def active_instances(self) -> list:
        active_ids = [m.id for m in self._manifests if self._state.get(m.id) == "ACTIVE"]
        active_ids.sort(key=lambda sid: (self._by_id[sid].priority, sid))
        return [self._instances[sid] for sid in active_ids]

    def instance_of(self, strategy_id):
        return self._instances.get(strategy_id)

    def id_of(self, instance):
        """Reverse lookup: manifest id for a live strategy instance (identity
        match, not equality — two instances of the same class are distinct).
        Returns None if the instance isn't one this registry loaded."""
        for sid, inst in self._instances.items():
            if inst is instance:
                return sid
        return None

    def state_of(self, strategy_id) -> str:
        return self._state.get(strategy_id)

    def priority_of(self, strategy_id) -> int:
        """Manifest priority for an id; 50 (the Intent default) when unknown."""
        manifest = self._by_id.get(strategy_id)
        return manifest.priority if manifest is not None else 50

    def report(self) -> list:
        return [
            {
                "id": m.id,
                "version": m.version,
                "family": m.family,
                "tf": m.timeframe,
                "status": m.status,
                "state": self._state.get(m.id),
                "priority": m.priority,
            }
            for m in self._manifests
        ]

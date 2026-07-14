"""Strategy manifest model + YAML loader (Plan 04 registry layer).

A manifest declares a strategy's identity, FeatureBus requirements, and
rollout status without importing the strategy class itself -- class
resolution/import is the registry's job, not this module's.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

_VALID_STATUSES = {"research", "demo", "live"}
_VALID_TIMEFRAMES = {"M5", "M15", "H1"}
_REQUIRED_KEYS = ("id", "version", "class_path", "family", "timeframe", "requires", "status")


class ManifestError(ValueError):
    """Raised when a manifest file is missing/malformed."""


@dataclass(frozen=True)
class StrategyManifest:
    id: str
    version: str
    class_path: str
    family: str
    timeframe: str
    requires: tuple[str, ...]
    status: str
    priority: int = 50
    honors_htf_bias: bool = True


def load_manifest(path) -> StrategyManifest:
    """Load and validate a single manifest YAML file."""
    fname = os.path.basename(str(path))
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ManifestError(f"{fname}: manifest root must be a mapping, got {type(data).__name__}")

    for key in _REQUIRED_KEYS:
        if key not in data or data[key] in (None, ""):
            raise ManifestError(f"{fname}: missing required field '{key}'")

    status = data["status"]
    if status not in _VALID_STATUSES:
        raise ManifestError(
            f"{fname}: field 'status' must be one of {sorted(_VALID_STATUSES)}, got {status!r}"
        )

    timeframe = data["timeframe"]
    if timeframe not in _VALID_TIMEFRAMES:
        raise ManifestError(
            f"{fname}: field 'timeframe' must be one of {sorted(_VALID_TIMEFRAMES)}, got {timeframe!r}"
        )

    class_path = data["class_path"]
    if not isinstance(class_path, str) or class_path.count(":") != 1:
        raise ManifestError(
            f"{fname}: field 'class_path' must contain exactly one ':' (module:ClassName), got {class_path!r}"
        )

    requires = data["requires"]
    if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
        raise ManifestError(f"{fname}: field 'requires' must be a list of strings")

    priority = data.get("priority", 50)
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise ManifestError(f"{fname}: field 'priority' must be an int, got {priority!r}")

    honors_htf_bias = data.get("honors_htf_bias", True)
    if not isinstance(honors_htf_bias, bool):
        raise ManifestError(
            f"{fname}: field 'honors_htf_bias' must be a boolean, got {honors_htf_bias!r}"
        )

    return StrategyManifest(
        id=data["id"],
        version=str(data["version"]),
        class_path=class_path,
        family=data["family"],
        timeframe=timeframe,
        requires=tuple(requires),
        status=status,
        priority=priority,
        honors_htf_bias=honors_htf_bias,
    )


def load_manifests(dir_path) -> list[StrategyManifest]:
    """Load all *.yaml manifests in dir_path, sorted by filename.

    Raises ManifestError on duplicate ids across the loaded set.
    """
    filenames = sorted(f for f in os.listdir(dir_path) if f.endswith(".yaml"))
    manifests: list[StrategyManifest] = []
    seen_ids: dict[str, str] = {}
    for fname in filenames:
        manifest = load_manifest(os.path.join(dir_path, fname))
        if manifest.id in seen_ids:
            raise ManifestError(
                f"{fname}: duplicate strategy id '{manifest.id}' (already loaded from {seen_ids[manifest.id]})"
            )
        seen_ids[manifest.id] = fname
        manifests.append(manifest)
    return manifests

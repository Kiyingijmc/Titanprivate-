"""Layered config: checked-in defaults deep-merged with GUI-written overrides."""
import copy
from pathlib import Path

import yaml


def deep_merge(base: dict, override: dict) -> dict:
    """New dict: override wins key-by-key; nested dicts merge; lists/scalars replace."""
    result = copy.deepcopy(base)
    for key, ovr_val in override.items():
        base_val = result.get(key)
        if isinstance(base_val, dict) and isinstance(ovr_val, dict):
            result[key] = deep_merge(base_val, ovr_val)
        else:
            result[key] = copy.deepcopy(ovr_val)
    return result


def load_layered_config(defaults_path: Path, overrides_path: Path) -> dict:
    with open(defaults_path, "r", encoding="utf-8") as f:
        defaults = yaml.safe_load(f) or {}
    overrides = {}
    if Path(overrides_path).exists():
        # overrides.yaml is machine-written (SettingsStore.set, non-atomic). A
        # truncated/invalid file must NEVER wedge startup (spec: "a bad override
        # must never wedge startup") — fall back to defaults-only and let the
        # caller surface the problem, rather than crashing the trading process.
        try:
            with open(overrides_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            overrides = loaded if isinstance(loaded, dict) else {}
        except (yaml.YAMLError, OSError):
            overrides = {}
    return deep_merge(defaults, overrides)

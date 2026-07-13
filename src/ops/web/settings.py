# src/ops/web/settings.py
"""Layered-config store: tagged effective view, validation, override persistence.

The safe-subset allowlist is the safety boundary — only these keys may ever be
applied to a running bot. Everything else is saved and flagged restart-required.
Strategy lifecycle is NOT here: the registry owns enable/disable/promote.
"""
import copy
import re
from pathlib import Path

import yaml

from .config_layer import deep_merge

_SAFE_PATTERNS = [
    r"signal_grading\.enabled",
    r"signal_grading\.min_grade",
    r"risk\.trade\.risk_per_trade_pct",
    r"risk\.account\.max_daily_drawdown_pct",
    r"risk\.account\.max_global_exposure_pct",
    r"risk\.drawdown_throttle\.enabled",
    r"risk\.drawdown_throttle\.trigger_dd_pct",
    r"risk\.drawdown_throttle\.factor",
    r"trade_management\.runner\.enabled",
    r"trade_management\.runner\.tighten_on_giveback",
    r"trade_management\.runner\.giveback_frac",
    r"trade_management\.runner\.tight_trail_frac",
]
_SAFE_RE = [re.compile(f"^{p}$") for p in _SAFE_PATTERNS]

_VALID_GRADES = {"A++", "A+", "A", "B", "C"}
_BOOL_KEYS = (".enabled", ".tighten_on_giveback")
_FRAC_KEYS = (".giveback_frac", ".tight_trail_frac", ".factor")


class SettingsStore:
    def __init__(self, defaults: dict, overrides_path: Path):
        self._defaults = copy.deepcopy(defaults)
        self._overrides_path = Path(overrides_path)
        self._overrides = {}
        if self._overrides_path.exists():
            self._overrides = yaml.safe_load(self._overrides_path.read_text()) or {}

    def is_safe(self, key: str) -> bool:
        return any(rx.match(key) for rx in _SAFE_RE)

    def validate(self, key: str, value):
        if key == "signal_grading.min_grade":
            return None if value in _VALID_GRADES else f"min_grade must be one of {sorted(_VALID_GRADES)}"
        if key.endswith(_BOOL_KEYS):
            return None if isinstance(value, bool) else "must be a boolean"
        if key.endswith(_FRAC_KEYS):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 <= value <= 1 else "must be in [0, 1]"
        if key.endswith("risk_per_trade_pct"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 < value <= 10 else "risk_per_trade_pct must be in (0, 10]"
        if key.endswith("_pct"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "must be a number"
            return None if 0 < value <= 100 else "percent must be in (0, 100]"
        return None  # restart-tier keys: saved as-is

    def effective(self) -> dict:
        return deep_merge(self._defaults, self._overrides)

    def describe(self) -> list:
        rows = []
        for key, value in _flatten(self.effective()):
            rows.append({"key": key, "value": value,
                         "source": "override" if _has_key(self._overrides, key) else "default",
                         "tier": "live" if self.is_safe(key) else "restart"})
        return rows

    def set(self, key: str, value) -> dict:
        err = self.validate(key, value)
        if err:
            raise ValueError(err)
        _set_key(self._overrides, key, value)
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self._overrides_path.write_text(yaml.safe_dump(self._overrides, sort_keys=False))
        safe = self.is_safe(key)
        return {"applied": "live" if safe else "on_restart",
                "restart_required": not safe, "value": value}


def _flatten(d: dict, prefix: str = ""):
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from _flatten(v, key)
        else:
            yield key, v


def _has_key(d: dict, dotted: str) -> bool:
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def _set_key(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value

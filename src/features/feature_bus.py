"""
FeatureBus: Token-keyed memoized resource DAG for feature computation.

PURITY CONTRACT:
All compute functions must be pure (deterministic, no side effects), as they are
memoized based on token and version. A compute function with side effects will
have those side effects suppressed on cache hits.

CACHE DESIGN (Latest-Entry-Only):
Cache keys are (name, symbol_key, token, version). Only the LATEST entry per
(name, symbol_key) is retained—a new token overwrites the old, even if versions
differ. This decision trades memory for implementation simplicity: the cache is
structurally bounded by (resources × symbols × timeframes), and no LRU eviction
is needed. At typical scale (50 resources, 10 symbols, 3 TFs), this is ~1500
entries, each holding a tiny result—well under memory pressure.

Deps are evaluated in topological order and share the evaluate() call's token,
window, and extra dict, enabling efficient reuse within a single frame.
"""

import time
from dataclasses import dataclass
from typing import Callable, Any


@dataclass(frozen=True)
class ResourceSpec:
    """Specification for a memoized resource in the feature bus."""
    name: str
    deps: tuple = ()
    scope: str = "symbol_tf"  # "symbol_tf" | "symbol" | "global"
    compute: Callable = None
    version: str = "1"


class ResourceCtx:
    """Context passed to a resource's compute function."""
    def __init__(self, window, deps, extra):
        self.window = window
        self.deps = deps
        self.extra = extra


class FeatureBus:
    """
    Token-keyed memoized resource DAG.

    Manages registration, validation, and evaluation of resources with
    dependency resolution, topological ordering, and per-token memoization.
    """

    def __init__(self):
        self._registry = {}  # name -> ResourceSpec
        self._cache = {}  # (name, symbol_key, token, version) -> value
        self._cache_keys = {}  # (name, symbol_key) -> (token, version) of latest entry
        self._stats = {}  # name -> {"hits": int, "misses": int, "compute_ms": float}

    def register(self, spec: ResourceSpec) -> None:
        """
        Register a resource spec.

        Args:
            spec: ResourceSpec to register

        Raises:
            ValueError: If a resource with the same name already exists
        """
        if spec.name in self._registry:
            raise ValueError(f"Resource '{spec.name}' already registered")
        self._registry[spec.name] = spec
        self._stats[spec.name] = {"hits": 0, "misses": 0, "compute_ms": 0.0}

    def validate(self) -> None:
        """
        Validate the resource graph.

        Checks for:
        - Cycles (using DFS with visiting-set)
        - Unknown dependencies

        Raises:
            ValueError: If cycles detected or unknown dependencies found
        """
        # Check for unknown deps
        for name, spec in self._registry.items():
            for dep in spec.deps:
                if dep not in self._registry:
                    raise ValueError(f"Resource '{name}' has unknown dependency '{dep}'")

        # Check for cycles using DFS
        for name in self._registry:
            visited = set()
            rec_stack = set()
            if self._has_cycle(name, visited, rec_stack):
                raise ValueError(f"Cycle detected involving resource '{name}'")

    def _has_cycle(self, node, visited, rec_stack):
        """DFS helper to detect cycles."""
        visited.add(node)
        rec_stack.add(node)

        for dep in self._registry[node].deps:
            if dep not in visited:
                if self._has_cycle(dep, visited, rec_stack):
                    return True
            elif dep in rec_stack:
                return True

        rec_stack.remove(node)
        return False

    def evaluate(self, name: str, symbol: str, tf: str, token: str,
                 window=None, **extra) -> Any:
        """
        Evaluate a resource, resolving all dependencies.

        Args:
            name: Resource name to evaluate
            symbol: Symbol context (e.g. "EURUSD")
            tf: Timeframe context (e.g. "H1")
            token: Token for memoization (e.g. bar ID, timestamp)
            window: Optional DataFrame context
            **extra: Additional kwargs passed to all dependencies

        Returns:
            Computed resource value

        Raises:
            KeyError: If resource name not found
        """
        if name not in self._registry:
            raise KeyError(f"Resource '{name}' not found")

        # Evaluate the resource and all its deps
        result_dict = {}
        self._evaluate_recursive(name, symbol, tf, token, window, extra, result_dict)
        return result_dict[name]

    def _evaluate_recursive(self, name: str, symbol: str, tf: str, token: str,
                           window, extra: dict, result_dict: dict) -> None:
        """
        Recursively evaluate a resource and its dependencies.

        Args:
            name: Resource name
            symbol: Symbol context
            tf: Timeframe context
            token: Memoization token
            window: Window DataFrame
            extra: Extra kwargs dict
            result_dict: Dict to accumulate results (modified in place)
        """
        if name in result_dict:
            return  # Already computed in this evaluate() call

        spec = self._registry[name]

        # Compute symbol_key based on scope
        if spec.scope == "symbol_tf":
            symbol_key = (symbol, tf)
        elif spec.scope == "symbol":
            symbol_key = symbol
        else:  # "global"
            symbol_key = None

        cache_key = (name, symbol_key, token, spec.version)
        cache_latest_key = (name, symbol_key)

        # Check cache
        if cache_latest_key in self._cache_keys:
            cached_token, cached_version = self._cache_keys[cache_latest_key]
            if cached_token == token and cached_version == spec.version:
                # Cache hit
                self._stats[name]["hits"] += 1
                result_dict[name] = self._cache[cache_key]
                return

        # Cache miss: evaluate deps first
        deps_dict = {}
        for dep_name in spec.deps:
            self._evaluate_recursive(dep_name, symbol, tf, token, window, extra, result_dict)
            deps_dict[dep_name] = result_dict[dep_name]

        # Compute this resource. A raising compute counts neither hit nor miss
        # and writes nothing to the cache (no half-written entries).
        ctx = ResourceCtx(window=window, deps=deps_dict, extra=extra)
        start_time = time.perf_counter()
        value = spec.compute(ctx)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        self._stats[name]["misses"] += 1
        self._stats[name]["compute_ms"] += elapsed_ms

        # Evict the superseded entry (latest-entry-only per (name, symbol_key)),
        # then store the new one. This keeps the cache structurally bounded.
        old_pointer = self._cache_keys.get(cache_latest_key)
        if old_pointer is not None:
            old_token, old_version = old_pointer
            self._cache.pop((name, symbol_key, old_token, old_version), None)
        self._cache[cache_key] = value
        self._cache_keys[cache_latest_key] = (token, spec.version)

        result_dict[name] = value

    def stats(self) -> dict:
        """
        Get statistics for all resources.

        Returns:
            Dict mapping resource name to {"hits": int, "misses": int, "compute_ms": float}
        """
        return {name: dict(stats) for name, stats in self._stats.items()}

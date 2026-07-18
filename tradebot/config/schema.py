"""tradebot.config.schema — Pydantic v2 config schema (M0-1).

Scope of this module (see docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md
§2.6 and §6.1, pass1-audit.md F-034/F-017/F-036, pass5-interfaces.md's binding-order
wording, and docs/trading-bot-brainstorm/04-architecture-config.md §B3-B4):

- F-034: the per-trade risk cap is re-clamped in the schema itself —
  ``effective_risk = min(risk_pct * vol_scalar, hard_cap)`` — so a volatility
  overlay can never compose past the hard cap "by validation, not by trust".
- F-017: every instrument declares exactly one asset_class (from a closed,
  config-declared set) and zero-or-more correlation_groups (from a declared
  set); every limit-stack row declares its gross/net counting mode explicitly.
- F-036: a binding-order report computes, from the currently configured limit
  values, which limits can mathematically bind and which are structurally
  dead (e.g. at defaults, 12 positions x 0.5% per-trade = 6% < the 8%
  account-total cap, so the account-total limit is dead under #1/#11).

This module is schema-only: it validates config shape, ranges, and static
membership. It deliberately does NOT implement the runtime limit-stack
ledger/aggregation engine (Sigma-risk across live positions) — that is
``risk/ledger.py``, a later milestone. It also does not consume CAL-row
(calendar-service-derived) ranges. ``tradebot`` is a new, independent package
and must not import from ``src/`` (the Titan v14 bot).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Reload-class tagging (04-architecture-config.md §B4)
# ---------------------------------------------------------------------------

ReloadClass = Literal["live", "next-signal", "restart"]
"""The three-way hot-reload split from §B4:

- ``live``: applied instantly via a config event (modes, enable/disable,
  risk %, timeouts, notification prefs).
- ``next-signal``: applied to new signals only; working orders keep their
  original contract (child params, instrument lists).
- ``restart``: flagged ``restart_required`` in the GUI (timeframes/feature
  graph, adapter choice, process topology, and — a deliberate v1 choice here
  — the safety caps themselves, so a live mistake can't silently widen a
  hard limit).
"""


def reload_field(*, reload_class: ReloadClass, **kwargs: Any) -> Any:
    """``Field()`` wrapper that stamps ``reload_class`` into ``json_schema_extra``
    so every field's hot-reload tier is introspectable (see
    ``ReloadTaggedModel.reload_classes``)."""

    json_schema_extra = dict(kwargs.pop("json_schema_extra", None) or {})
    json_schema_extra["reload_class"] = reload_class
    return Field(json_schema_extra=json_schema_extra, **kwargs)


class ReloadTaggedModel(BaseModel):
    """Base class for config models: forbids unknown keys (a bad config must
    never silently partially-apply, §B3) and exposes each field's reload
    class."""

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def reload_classes(cls) -> dict[str, ReloadClass]:
        """Return ``{field_name: reload_class}`` for every field on this
        model that carries a reload-class tag (own fields only, not nested
        sub-models — callers that need the full tree should recurse)."""

        result: dict[str, ReloadClass] = {}
        for field_name, info in cls.model_fields.items():
            extra = info.json_schema_extra
            if isinstance(extra, dict) and "reload_class" in extra:
                result[field_name] = extra["reload_class"]
        return result


# ---------------------------------------------------------------------------
# Limit #1 (pass3 §2.6): per-trade risk cap + F-034 re-clamp
# ---------------------------------------------------------------------------


class PerTradeRiskConfig(ReloadTaggedModel):
    """Limit #1 of the pass3 §2.6 limit stack: per-trade risk, with the
    volatility-targeting overlay re-clamped against a hard cap (F-034).

    Pass-1 finding: "T3 configured at 1.0%; low realized vol => x1.5 =>
    1.5% per-trade risk approved by the very layer whose one job is the
    cap." The fix (pass3 §2.6 row #1): ``effective_risk = min(risk_pct *
    vol_scalar, hard_cap)`` — enforced here as a computed field plus a
    model-validator that pins the invariant as an executable assertion
    (not just documentation), so it cannot silently regress if the formula
    is ever edited.
    """

    risk_pct: float = reload_field(
        default=0.5,
        ge=0.0,
        le=100.0,
        reload_class="live",
        description="Configured per-trade risk percent, before vol-scalar scaling.",
    )
    vol_scalar: float = reload_field(
        default=1.0,
        ge=0.5,
        le=1.5,
        reload_class="live",
        description="Volatility-targeting overlay multiplier (pass3 §2.6 limit #1 range [0.5, 1.5]).",
    )
    hard_cap: float = reload_field(
        default=1.0,
        ge=0.0,
        le=100.0,
        reload_class="restart",
        description="Absolute per-trade risk ceiling (F-034); effective_risk must never exceed this.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_risk(self) -> float:
        """F-034 re-clamp: ``min(risk_pct * vol_scalar, hard_cap)``."""

        return min(self.risk_pct * self.vol_scalar, self.hard_cap)

    @model_validator(mode="after")
    def _f034_reclamp_never_exceeds_hard_cap(self) -> "PerTradeRiskConfig":
        if self.effective_risk - self.hard_cap > 1e-9:
            raise ValueError(
                f"F-034 violation: effective_risk={self.effective_risk!r} "
                f"exceeds hard_cap={self.hard_cap!r} "
                f"(risk_pct={self.risk_pct!r}, vol_scalar={self.vol_scalar!r})"
            )
        return self


# ---------------------------------------------------------------------------
# Limits #2-#11 (pass3 §2.6): declared gross/net counting mode + ranges
# ---------------------------------------------------------------------------

CountingMode = Literal["gross", "net", "count", "n/a"]
"""How a limit's rows are aggregated (F-017): ``gross`` = sum of absolute
values, ``net`` = sum of signed values, ``count`` = a plain count (limit
#11), ``n/a`` = not applicable (limit #1, a single-trade check)."""


class LimitRow(ReloadTaggedModel):
    """One numeric row of the pass3 §2.6 limit-stack table. Schema-only:
    declares the configured value and its counting mode explicitly (F-017)
    so gross/net ambiguity cannot silently creep back in. Does not perform
    any runtime Sigma-aggregation — that is ``risk/ledger.py``, a later
    milestone."""

    value_pct: float = reload_field(
        default=...,
        ge=0.0,
        le=1000.0,
        reload_class="restart",
        description="Configured limit value, in percent (or percent-of-equity multiple for notional caps).",
    )
    counting_mode: CountingMode = reload_field(
        default=...,
        reload_class="restart",
        description="Explicit gross/net/count aggregation mode for this limit row (F-017).",
    )


class LimitStackConfig(ReloadTaggedModel):
    """Limits #2-#11 of the pass3 §2.6 table (limit #1 is
    ``PerTradeRiskConfig``, above). Defaults match the table's "Default"
    column. Schema-only: ranges, types, and explicit counting-mode
    declarations — no runtime ledger aggregation."""

    per_instrument_open_risk: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=1.5, counting_mode="gross"),
        reload_class="restart",
        description="Limit #2: per-instrument open risk.",
    )
    per_child_open_risk: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=2.0, counting_mode="gross"),
        reload_class="restart",
        description="Limit #3: per-child open risk.",
    )
    per_asset_class: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=4.0, counting_mode="gross"),
        reload_class="restart",
        description="Limit #4: per-asset-class open risk.",
    )
    per_correlation_group: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=4.0, counting_mode="net"),
        reload_class="restart",
        description="Limit #5: per-correlation-group open risk (signed).",
    )
    macro_factor_cap: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=5.0, counting_mode="net"),
        reload_class="restart",
        description="Limit #6: macro-factor cap (hypothesis default; per-factor loadings deferred to risk/ledger.py).",
    )
    account_total_open_risk: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=8.0, counting_mode="gross"),
        reload_class="restart",
        description="Limit #7: account-total open risk.",
    )
    gap_stressed_account_total: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=12.0, counting_mode="gross"),
        reload_class="restart",
        description="Limit #8: gap-stressed account total (hypothesis default).",
    )
    margin_utilization: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=25.0, counting_mode="gross"),
        reload_class="restart",
        description="Limit #9: margin utilization (hypothesis default; Sigma margin/equity, a different basis than risk-at-stop).",
    )
    notional_per_asset_class: LimitRow = reload_field(
        default_factory=lambda: LimitRow(value_pct=600.0, counting_mode="gross"),
        reload_class="restart",
        description=(
            "Limit #10: notional per class, expressed as percent-of-equity "
            "(hypothesis default, fx's 6x shown as 600%); per-class "
            "multipliers (fx 6x / metal 3x / index 2x / crypto 1x) are "
            "deferred to risk/ledger.py — this pins a single composite "
            "range check for now."
        ),
    )
    max_positions: int = reload_field(
        default=12,
        ge=1,
        le=1000,
        reload_class="restart",
        description="Limit #11: max open positions (sanity backstop).",
    )


# ---------------------------------------------------------------------------
# F-017: asset-class / correlation-group membership
# ---------------------------------------------------------------------------


class AssetClassDef(ReloadTaggedModel):
    """One entry in the closed set of declared asset classes (F-017)."""

    name: str = reload_field(default=..., reload_class="restart")


class CorrelationGroupDef(ReloadTaggedModel):
    """One entry in the declared set of correlation groups (F-017)."""

    name: str = reload_field(default=..., reload_class="restart")


class InstrumentConfig(ReloadTaggedModel):
    """One traded instrument. Must declare exactly one asset class and may
    declare zero or more correlation groups (F-017) — e.g. gold declares
    ``asset_classes=["metal"]`` and ``correlation_groups=["safe_haven"]``;
    multi correlation-group membership is legal, multi asset-class
    membership is not."""

    symbol: str = reload_field(
        default=...,
        reload_class="next-signal",
        description="Broker-exact symbol name.",
    )
    asset_classes: list[str] = reload_field(
        default=...,
        reload_class="next-signal",
        description="Must contain exactly one name from the declared closed asset-class set (F-017).",
    )
    correlation_groups: list[str] = reload_field(
        default_factory=list,
        reload_class="next-signal",
        description="Zero or more names from the declared correlation-group set (F-017); multi-membership is legal.",
    )

    @field_validator("asset_classes")
    @classmethod
    def _exactly_one_asset_class(cls, v: list[str]) -> list[str]:
        if len(v) != 1:
            raise ValueError(
                f"instrument must declare exactly one asset_class, got {len(v)}: {v!r}"
            )
        return v

    @property
    def asset_class(self) -> str:
        """The single declared asset class (convenience accessor)."""

        return self.asset_classes[0]


class InstrumentsConfig(ReloadTaggedModel):
    """The declared asset-class/correlation-group taxonomy plus the
    instrument list, with F-017 membership validation: every instrument's
    ``asset_class`` must be in the declared closed set, and every
    ``correlation_groups`` entry must be in the declared group set."""

    asset_classes: list[AssetClassDef] = reload_field(
        default_factory=list,
        reload_class="restart",
        description="The closed set of declared asset classes (F-017).",
    )
    correlation_groups: list[CorrelationGroupDef] = reload_field(
        default_factory=list,
        reload_class="restart",
        description="The declared set of correlation groups (F-017).",
    )
    instruments: list[InstrumentConfig] = reload_field(
        default_factory=list,
        reload_class="next-signal",
        description="The traded instrument list (04-architecture-config.md §B4: next-signal class).",
    )

    @model_validator(mode="after")
    def _validate_membership(self) -> "InstrumentsConfig":
        declared_classes = {c.name for c in self.asset_classes}
        declared_groups = {g.name for g in self.correlation_groups}
        for inst in self.instruments:
            if inst.asset_class not in declared_classes:
                raise ValueError(
                    f"instrument {inst.symbol!r}: asset_class {inst.asset_class!r} "
                    f"is not in the declared asset_classes {sorted(declared_classes)!r}"
                )
            bad_groups = [g for g in inst.correlation_groups if g not in declared_groups]
            if bad_groups:
                raise ValueError(
                    f"instrument {inst.symbol!r}: correlation_groups {bad_groups!r} "
                    f"are not in the declared correlation_groups {sorted(declared_groups)!r}"
                )
        return self


# ---------------------------------------------------------------------------
# F-036: binding-order report
# ---------------------------------------------------------------------------

# Limits measured in the same basis as the per-trade-risk x max-positions
# ceiling (raw Sigma risk-at-stop, gross or net, percent of equity) — these
# are the ones the ceiling argument can actually prove dead or not:
# #6's loadings are bounded in [-1, 1], so Sigma|risk x loading| <= Sigma|risk|
# <= ceiling, and the same "cannot exceed" reasoning applies.
#
# Deliberately excluded:
# - #8 gap_stressed_account_total is a *stressed* (multiplied) exposure
#   basis, not raw risk-at-stop — pass3 §2.6 notes it "binds on Fridays for
#   index CFDs, by design", i.e. it is expected to exceed the raw ceiling
#   under stress, so "ceiling < value" would not safely prove it dead.
# - #9 (margin) and #10 (notional) are different aggregation bases entirely
#   (margin/equity, notional/equity) and are excluded rather than mislabeled.
_CEILING_COMPARABLE_LIMITS: tuple[tuple[int, str], ...] = (
    (2, "per_instrument_open_risk"),
    (3, "per_child_open_risk"),
    (4, "per_asset_class"),
    (5, "per_correlation_group"),
    (6, "macro_factor_cap"),
    (7, "account_total_open_risk"),
)


class LimitBindingStatus(BaseModel):
    """Whether one limit-stack row can mathematically bind given the current
    per-trade x max-positions ceiling (F-036)."""

    number: int
    name: str
    dead: bool
    reason: str


class BindingOrderReport(BaseModel):
    """F-036: which configured limits can bind and which are structurally
    dead, matching the pass3 §2.6 / pass5 wording pattern (e.g. "limit #7
    dead under current #1/#11 — binding limits: #2,#4,#6,#8")."""

    statuses: list[LimitBindingStatus]

    @property
    def dead_limits(self) -> list[LimitBindingStatus]:
        return [s for s in self.statuses if s.dead]

    @property
    def binding_limits(self) -> list[LimitBindingStatus]:
        return [s for s in self.statuses if not s.dead]

    def is_dead(self, number: int) -> bool:
        for s in self.statuses:
            if s.number == number:
                return s.dead
        raise KeyError(f"limit #{number} not present in this report")

    def render(self) -> str:
        if not self.dead_limits:
            return "all limits can bind under current settings"
        binding_nums = ",".join(f"#{b.number}" for b in self.binding_limits)
        lines = [
            f"limit #{d.number} ({d.name}) dead under current #1/#11 — binding limits: {binding_nums}"
            for d in self.dead_limits
        ]
        return "\n".join(lines)


def compute_binding_order(
    *,
    per_trade_effective_risk_pct: float,
    max_positions: int,
    limit_stack: LimitStackConfig,
) -> BindingOrderReport:
    """F-036: for every ceiling-comparable limit row, determine whether the
    maximum possible aggregate exposure permitted by limit #1 (per-trade
    effective risk) and limit #11 (max positions) already falls under that
    row's threshold — i.e. the position/size caps bind first and the
    higher-scope limit can never be reached.

    Pinned example (pass3 §2.6 defaults): 12 positions x 0.5% = 6% < the 8%
    account-total cap, so limit #7 is dead under #1/#11.
    """

    ceiling = per_trade_effective_risk_pct * max_positions
    statuses: list[LimitBindingStatus] = []
    for number, field_name in _CEILING_COMPARABLE_LIMITS:
        row: LimitRow = getattr(limit_stack, field_name)
        dead = ceiling < row.value_pct
        if dead:
            reason = (
                f"{max_positions} x {per_trade_effective_risk_pct:g}% = {ceiling:g}% "
                f"< {row.value_pct:g}% under current #1/#11"
            )
        else:
            reason = (
                f"{max_positions} x {per_trade_effective_risk_pct:g}% = {ceiling:g}% "
                f">= {row.value_pct:g}%: can bind"
            )
        statuses.append(LimitBindingStatus(number=number, name=field_name, dead=dead, reason=reason))
    return BindingOrderReport(statuses=statuses)


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class TradebotConfig(ReloadTaggedModel):
    """M0-1 top-level config skeleton. Only the pieces needed to close
    F-034/F-017/F-036 are modeled here; ``config/defaults.yaml``, broker
    overlays, and the runtime limit-stack ledger are later milestones (see
    pass3-systems.md §6.1)."""

    risk: PerTradeRiskConfig = reload_field(
        default_factory=PerTradeRiskConfig,
        reload_class="live",
        description="Limit #1: per-trade risk (04-architecture-config.md §B4: risk % is live-reloadable).",
    )
    limit_stack: LimitStackConfig = reload_field(
        default_factory=LimitStackConfig,
        reload_class="restart",
        description="Limits #2-#11: safety caps only take effect after a restart.",
    )
    instruments: InstrumentsConfig = reload_field(
        default_factory=InstrumentsConfig,
        reload_class="next-signal",
        description="Asset-class/correlation-group taxonomy + instrument list.",
    )

    def binding_order_report(self) -> BindingOrderReport:
        """F-036: compute which of this config's limits are dead/binding."""

        return compute_binding_order(
            per_trade_effective_risk_pct=self.risk.effective_risk,
            max_positions=self.limit_stack.max_positions,
            limit_stack=self.limit_stack,
        )


__all__ = [
    "ReloadClass",
    "reload_field",
    "ReloadTaggedModel",
    "PerTradeRiskConfig",
    "CountingMode",
    "LimitRow",
    "LimitStackConfig",
    "AssetClassDef",
    "CorrelationGroupDef",
    "InstrumentConfig",
    "InstrumentsConfig",
    "LimitBindingStatus",
    "BindingOrderReport",
    "compute_binding_order",
    "TradebotConfig",
]

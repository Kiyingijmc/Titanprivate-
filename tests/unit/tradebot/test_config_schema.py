"""Unit tests for tradebot.config.schema (M0-1).

Covers the three Pass-1 register findings this schema is meant to
structurally foreclose (see docs/trading-bot-brainstorm/brainstorm-v2/
pass1-audit.md and pass3-systems.md §2.6):

- F-034: per-trade risk cap re-clamp (vol_scalar composition can't breach
  hard_cap).
- F-017: asset-class / correlation-group membership rules.
- F-036: binding-order report (dead vs binding limits).

Plus a reload-class tagging check (04-architecture-config.md §B4).
"""

import unittest

from pydantic import ValidationError

from tradebot.config.schema import (
    AssetClassDef,
    CorrelationGroupDef,
    InstrumentConfig,
    InstrumentsConfig,
    LimitStackConfig,
    PerTradeRiskConfig,
    ReloadTaggedModel,
    TradebotConfig,
)


class TestF034PerTradeRiskReclamp(unittest.TestCase):
    """F-034: effective_risk = min(risk_pct * vol_scalar, hard_cap)."""

    def test_effective_risk_clamped_to_hard_cap(self):
        # The Pass-1 register example: T3 at 1.0% x 1.5 vol_scalar must not
        # silently approve 1.5% — it must clamp to the 1.0% hard cap.
        cfg = PerTradeRiskConfig(risk_pct=1.0, vol_scalar=1.5, hard_cap=1.0)
        self.assertAlmostEqual(cfg.effective_risk, 1.0)

    def test_clamp_has_teeth_against_a_naive_unclamped_formula(self):
        # A naive `risk_pct * vol_scalar` (no re-clamp) is exactly the bug
        # F-034 describes: "the cap ... is breached by an interaction, not
        # a key". Prove the schema's actual value diverges from that naive
        # product at the documented boundary case, i.e. the clamp is doing
        # real work here, not a no-op.
        risk_pct, vol_scalar, hard_cap = 1.0, 1.5, 1.0
        naive_unclamped = risk_pct * vol_scalar
        cfg = PerTradeRiskConfig(risk_pct=risk_pct, vol_scalar=vol_scalar, hard_cap=hard_cap)
        self.assertEqual(naive_unclamped, 1.5)
        self.assertNotAlmostEqual(cfg.effective_risk, naive_unclamped)
        self.assertLessEqual(cfg.effective_risk, hard_cap)

    def test_below_cap_is_passed_through_unclamped(self):
        cfg = PerTradeRiskConfig(risk_pct=0.5, vol_scalar=1.0, hard_cap=1.0)
        self.assertAlmostEqual(cfg.effective_risk, 0.5)

    def test_vol_scalar_out_of_documented_range_rejected(self):
        # pass3 §2.6 limit #1: vol_scalar in [0.5, 1.5].
        with self.assertRaises(ValidationError):
            PerTradeRiskConfig(risk_pct=0.5, vol_scalar=1.6, hard_cap=1.0)
        with self.assertRaises(ValidationError):
            PerTradeRiskConfig(risk_pct=0.5, vol_scalar=0.4, hard_cap=1.0)

    def test_effective_risk_never_exceeds_hard_cap_across_the_full_vol_scalar_range(self):
        for hundredths in range(50, 151):  # 0.50 .. 1.50 step 0.01
            vol_scalar = hundredths / 100
            cfg = PerTradeRiskConfig(risk_pct=1.0, vol_scalar=vol_scalar, hard_cap=1.0)
            self.assertLessEqual(cfg.effective_risk, 1.0 + 1e-9)


class TestF017AssetClassAndCorrelationGroups(unittest.TestCase):
    """F-017: exactly-one asset_class, zero-or-more correlation_groups,
    both validated against declared closed sets."""

    def _instruments_config(self, instruments):
        return InstrumentsConfig(
            asset_classes=[AssetClassDef(name="metal"), AssetClassDef(name="index")],
            correlation_groups=[
                CorrelationGroupDef(name="safe_haven"),
                CorrelationGroupDef(name="risk_on"),
            ],
            instruments=instruments,
        )

    def test_gold_like_multi_correlation_group_membership_accepted(self):
        # metal asset_class AND safe_haven correlation_group — multi
        # correlation-group membership is legal (only asset_class is
        # exclusive).
        cfg = self._instruments_config(
            [InstrumentConfig(symbol="XAUUSD", asset_classes=["metal"], correlation_groups=["safe_haven"])]
        )
        inst = cfg.instruments[0]
        self.assertEqual(inst.asset_class, "metal")
        self.assertEqual(inst.correlation_groups, ["safe_haven"])

    def test_instrument_may_belong_to_multiple_correlation_groups(self):
        cfg = self._instruments_config(
            [
                InstrumentConfig(
                    symbol="NAS100",
                    asset_classes=["index"],
                    correlation_groups=["risk_on", "safe_haven"],
                )
            ]
        )
        self.assertEqual(set(cfg.instruments[0].correlation_groups), {"risk_on", "safe_haven"})

    def test_zero_asset_classes_rejected(self):
        with self.assertRaises(ValidationError):
            InstrumentConfig(symbol="XAUUSD", asset_classes=[], correlation_groups=[])

    def test_two_asset_classes_rejected(self):
        with self.assertRaises(ValidationError):
            InstrumentConfig(symbol="XAUUSD", asset_classes=["metal", "index"], correlation_groups=[])

    def test_asset_class_not_in_declared_closed_set_rejected(self):
        with self.assertRaises(ValidationError):
            self._instruments_config(
                [InstrumentConfig(symbol="BTCUSD", asset_classes=["crypto"], correlation_groups=[])]
            )

    def test_correlation_group_not_in_declared_set_rejected(self):
        with self.assertRaises(ValidationError):
            self._instruments_config(
                [
                    InstrumentConfig(
                        symbol="XAUUSD", asset_classes=["metal"], correlation_groups=["nonexistent_group"]
                    )
                ]
            )


class TestF036BindingOrderReport(unittest.TestCase):
    """F-036: pass3 §2.6 default numbers — 12 x 0.5% = 6% < 8% means the
    account-total limit (#7) is dead under #1/#11."""

    def test_default_config_account_total_limit_is_dead(self):
        cfg = TradebotConfig()
        self.assertEqual(cfg.risk.effective_risk, 0.5)
        self.assertEqual(cfg.limit_stack.max_positions, 12)
        self.assertEqual(cfg.limit_stack.account_total_open_risk.value_pct, 8.0)

        report = cfg.binding_order_report()

        self.assertTrue(report.is_dead(7), "limit #7 (account-total) should be flagged dead at pass3 §2.6 defaults")
        rendered = report.render()
        self.assertIn("#7", rendered)
        self.assertIn("dead", rendered)

    def test_default_config_smaller_scope_limits_are_not_dead(self):
        # Limits #2/#3/#4/#5/#6 all sit below the 6% ceiling at defaults, so
        # they remain reachable (not dead) — only the 8% account-total is
        # structurally unreachable.
        cfg = TradebotConfig()
        report = cfg.binding_order_report()
        for number in (2, 3, 4, 5, 6):
            self.assertFalse(report.is_dead(number), f"limit #{number} should not be dead at defaults")

    def test_raising_max_positions_makes_account_total_reachable(self):
        # 16 x 0.5% = 8% == the account-total cap: no longer strictly under
        # it, so the limit should no longer be reported dead.
        cfg = TradebotConfig(
            limit_stack=LimitStackConfig(max_positions=16),
        )
        report = cfg.binding_order_report()
        self.assertFalse(report.is_dead(7))


class TestReloadClassTagging(unittest.TestCase):
    """04-architecture-config.md §B4: every field carries one of the three
    reload-class tags."""

    VALID_CLASSES = {"live", "next-signal", "restart"}

    def _assert_all_fields_tagged(self, model_cls):
        tags = model_cls.reload_classes()
        self.assertEqual(
            set(tags.keys()),
            set(model_cls.model_fields.keys()),
            f"{model_cls.__name__}: every field must carry a reload-class tag",
        )
        for field_name, reload_class in tags.items():
            self.assertIn(
                reload_class,
                self.VALID_CLASSES,
                f"{model_cls.__name__}.{field_name}: {reload_class!r} is not a valid reload class",
            )

    def test_top_level_config_fields_all_tagged(self):
        self._assert_all_fields_tagged(TradebotConfig)

    def test_nested_config_models_all_tagged(self):
        for model_cls in (
            PerTradeRiskConfig,
            LimitStackConfig,
            InstrumentsConfig,
            InstrumentConfig,
            AssetClassDef,
            CorrelationGroupDef,
        ):
            self._assert_all_fields_tagged(model_cls)

    def test_reload_class_matches_the_documented_three_way_split(self):
        # 04-architecture-config.md §B4 worked examples: risk % is live;
        # instrument lists are next-signal.
        self.assertEqual(TradebotConfig.reload_classes()["risk"], "live")
        self.assertEqual(PerTradeRiskConfig.reload_classes()["risk_pct"], "live")
        self.assertEqual(InstrumentsConfig.reload_classes()["instruments"], "next-signal")

    def test_every_config_model_subclasses_the_reload_tagged_base(self):
        for model_cls in (
            TradebotConfig,
            PerTradeRiskConfig,
            LimitStackConfig,
            InstrumentsConfig,
            InstrumentConfig,
        ):
            self.assertTrue(issubclass(model_cls, ReloadTaggedModel))


if __name__ == "__main__":
    unittest.main()

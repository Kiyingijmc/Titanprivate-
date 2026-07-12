"""
SMC feature pack: registers the two v14 SMC analyzers as FeatureBus resources.

Wraps existing pure analyzers with no behavior change:
- smc.enriched_df   -> SMCAnalyzer(window).process()      (scope: symbol_tf)
- smc.bias_context  -> BiasEngine(h1_df).get_bias_context() (scope: symbol)

Callers are responsible for picking a token that reflects the underlying
data's freshness (e.g. the window's/H1 frame's last bar time) so repeated
evaluates within the same bar are cache hits.
"""

from src.features.feature_bus import ResourceSpec
from src.analysis.smc_analyzer import SMCAnalyzer
from src.analysis.bias_engine import BiasEngine


def _compute_enriched_df(ctx):
    return SMCAnalyzer(ctx.window).process()


def _compute_bias_context(ctx):
    return BiasEngine(ctx.extra["h1_df"]).get_bias_context()


def register_smc_pack(bus) -> None:
    """Register the SMC resources on the given FeatureBus."""
    bus.register(ResourceSpec(
        name="smc.enriched_df",
        scope="symbol_tf",
        compute=_compute_enriched_df,
    ))
    bus.register(ResourceSpec(
        name="smc.bias_context",
        scope="symbol",
        compute=_compute_bias_context,
    ))

#!/usr/bin/env python3
# scripts/research_run.py
# Plan 06 / Task 4: research run CLI -- gate studies through the LIVE kernel,
# with a reproducibility run-card.
#
# Drives src/research/kernel_replay.py::replay() -- the same SystemController
# code path the live bot runs (real FeatureBus/smc pack, real Arbiter, real
# SignalGrader) -- over CSV or research-lake data, resolves each signal to a
# trade with the validated backtest math (tests/backtest/backtest_engine.py:
# resolve_trade/trade_dollars/split_trades/aggregate_metrics -- imported, never
# reimplemented), and writes a run-card (run.json + signals.jsonl) so every
# gate study is reproducible.
#
#   .venv/bin/python scripts/research_run.py --csv test_data.csv --symbol BTCUSD \
#       --tf H1 --strategy silver_bullet --spread-pips 20 --out data/results
#   .venv/bin/python scripts/research_run.py --lake-symbol EURUSD --tf H1 \
#       --strategy silver_bullet --out data/results
#
# Cost model: net R comes from tests.backtest.backtest_engine.trade_dollars,
# NOT scripts/poc_sb_stops.cost_r. cost_r imports cleanly (verified: only
# module-level imports/constants/function defs, no side effects), but it
# bakes in a hardcoded per-symbol SPREADS table and takes a `spread_mult`
# *multiplier* on that table -- there is no way to hand it an absolute
# --spread-pips value. trade_dollars takes `spread_points` explicitly, which
# is a direct fit for this CLI's --spread-pips contract, and it sizes from the
# same broker tick specs (data/specs.json) RiskManager uses live.
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "backtest"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml  # noqa: E402

import backtest_engine as bt  # noqa: E402
from lake_import import sniff_and_read, infer_symbol_tf  # noqa: E402
from src.data.lake import Lake, LakeError  # noqa: E402
from src.research.kernel_replay import replay, load_h1_from_m5  # noqa: E402
from src.strategies.manifest import load_manifests, ManifestError  # noqa: E402
from src.strategies.registry import StrategyRegistry, RegistryError  # noqa: E402

DEFAULT_CONFIG_PATH = os.path.join(REPO_ROOT, "config", "config.yaml")
DEFAULT_MANIFEST_DIR = os.path.join(REPO_ROOT, "config", "manifests")
DEFAULT_SPECS_PATH = os.path.join(REPO_ROOT, "data", "specs.json")

# Nominal sizing basis for the cost model. Only net R (the ratio) flows into
# the run-card/report -- the dollar figure itself is never surfaced -- but
# trade_dollars floors lot size to a step, so the exact value has a (tiny,
# documented) effect on net R; recorded in the run-card for reproducibility.
DEFAULT_RISK_DOLLARS = 1000.0
_DEFAULT_SPEC = {"tick_size": 1e-5, "tick_value": 1.0, "vol_step": 0.01}

_TF_CHOICES = ("H1",)


class _NullLogger:
    """No-op logger satisfying log_event(type, module, msg, payload=...), the
    same contract strategies/registry expect (mirrors tests/backtest's
    MockLogger and kernel_replay's _StubLogger)."""

    def log_event(self, *args, **kwargs):
        pass


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_config(path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _load_specs(path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _ensure_tick_volume(df):
    """Normalize the volume column to 'tick_volume' (matches
    backtest_engine.Backtester's rename_map + default-to-1 fallback), the
    column name load_h1_from_m5's resample step requires."""
    df = df.copy()
    if "tick_volume" not in df.columns:
        df["tick_volume"] = df["volume"] if "volume" in df.columns else 1
    return df


def _load_csv_h1(path, tf):
    """Read a CSV via the T2 sniffing readers, then resample to H1 if the
    requested tf is H1 (idempotent for data that is already hourly-aligned:
    each hour bucket holds exactly one row, so the aggregation returns it
    unchanged)."""
    raw = sniff_and_read(path)
    if tf != "H1":
        return raw[["time", "open", "high", "low", "close"]].reset_index(drop=True)
    raw = _ensure_tick_volume(raw)
    return load_h1_from_m5(raw)


def _load_lake_h1(lake_root, broker, symbol, tf):
    """Load `symbol`'s H1 bars from the lake, matching the CSV path's
    fallback: if H1 partitions aren't there, load M5 partitions for the same
    symbol/broker and resample with load_h1_from_m5 (the T3 helper, imported
    -- never re-derived; see _load_csv_h1). If M5 is missing too, raise one
    LakeError naming both misses (Lake.load's own message already names the
    broker/symbol/tf it looked for, so nesting both messages covers both).

    Returns (df_h1, source) -- `source` names what was actually loaded (H1
    partitions directly, or M5 partitions + the resample), so the run-card's
    data.source field stays truthful about the real path taken.
    """
    lake = Lake(lake_root)
    try:
        df_h1 = lake.load(symbol, tf=tf, broker=broker)
        return df_h1, f"lake:{broker}/{symbol}/{tf}"
    except LakeError as h1_err:
        try:
            df_m5 = lake.load(symbol, tf="M5", broker=broker)
        except LakeError as m5_err:
            raise LakeError(
                f"{h1_err}; M5 fallback also unavailable: {m5_err}"
            ) from m5_err
        df_m5 = _ensure_tick_volume(df_m5)
        df_h1 = load_h1_from_m5(df_m5)
        return df_h1, f"lake:{broker}/{symbol}/M5->H1(resampled)"


def _build_strategy(strategy_id, config, manifest_dir):
    """Construct the strategy instance the same way the live boot sequence
    does (src/core/system_controller.py::_init_strategies): load every
    manifest, hand each its config.yaml params block, instantiate via
    StrategyRegistry. research-status strategies are fine here (this is
    offline) -- we read the instance straight off the registry rather than
    calling activate_eligible(), which gates on demo/live status only."""
    manifests = load_manifests(manifest_dir)
    ids = sorted(m.id for m in manifests)
    if strategy_id not in ids:
        raise ValueError(f"unknown strategy id '{strategy_id}'; available: {ids}")

    params_by_id = config.get("strategies", {})
    registry = StrategyRegistry(manifests, params_by_id, _NullLogger())
    registry.load_all()
    instance = registry.instance_of(strategy_id)
    manifest = next(m for m in manifests if m.id == strategy_id)
    return instance, manifest


def _signals_to_trades(records, df_h1, spread_points, spec, commission_per_lot, max_lots):
    """Resolve executed signals into trades under ONE-open-per-symbol
    concurrency (tests.backtest.backtest_engine.simulate_signals -- imported,
    never reimplemented; it walks signals chronologically and skips any that
    arrive while a prior trade/limit still occupies the symbol).

    LIMIT signals rest at the decision price with the live 12-bar TTL
    (backtest_engine.py:401 convention). MARKET signals fill at the NEXT
    bar's open -- decision on bar-close i, fill at i+1 open; resolution only
    ever consults bars[bar_idx+1:], so there is no same-bar look-ahead. A
    MARKET decision on the final bar has no next open and is dropped.

    Returns (trades, skipped): `trades` are resolved rows with net R attached
    (gross R -> dollars via trade_dollars -> net R, same as before);
    `skipped` are busy-skipped signals journaled as outcome="SKIPPED_BUSY"
    (filled=False, r=0) so signals.jsonl remains a complete per-signal
    record. (A signal simulate_signals drops as INVALID -- zero risk -- also
    lands in `skipped`; with grader-passed decisions that is theoretical.)
    """
    bars = df_h1.to_dict("records")
    sigs = []
    for rec in records:
        if rec["signal"] is None:
            continue
        bar_idx = rec["i"] - 1
        cmd = rec.get("type") or "LIMIT"
        if cmd == "MARKET":
            if bar_idx + 1 >= len(bars):
                continue  # no next bar to fill on
            entry = float(bars[bar_idx + 1]["open"])
        else:
            entry = float(rec["price"])
        sigs.append({**rec, "bar_idx": bar_idx, "dir": rec["signal"], "cmd": cmd,
                     "entry": entry, "sl": float(rec["sl"]), "tp": float(rec["tp"]),
                     "ttl_bars": 12})

    resolved = bt.simulate_signals(sigs, bars)
    taken_idx = {t["bar_idx"] for t in resolved}

    trades = []
    for t in resolved:
        risk = abs(t["entry"] - t["sl"])
        dollars = bt.trade_dollars(
            t["r"], t["entry"], t["sl"], spec,
            spread_points, commission_per_lot, DEFAULT_RISK_DOLLARS, max_lots=max_lots,
        )
        net_r = (dollars["net"] / DEFAULT_RISK_DOLLARS) if DEFAULT_RISK_DOLLARS else 0.0
        trades.append({**t, "risk": risk, "gross_r": t["r"], "r": net_r})

    skipped = [{**s, "filled": False, "outcome": "SKIPPED_BUSY", "r": 0.0,
                "gross_r": 0.0, "risk": abs(s["entry"] - s["sl"])}
               for s in sigs if s["bar_idx"] not in taken_idx]
    return trades, skipped


def _print_report(card, run_dir):
    sp = card["spread_assumption"]
    print(f"[RESEARCH_RUN] strategy={card['strategy']['id']} v{card['strategy']['version']} "
          f"data={card['data']['source']} bars={card['n_bars']} "
          f"signals={card['n_signals']} trades={card['n_trades']}")
    print(f"[RESEARCH_RUN] cost_model={sp['cost_model']} spread_pips={sp['spread_pips']} "
          f"commission_per_lot={sp['commission_per_lot']} risk_dollars={sp['risk_dollars']}")
    for split_name in ("is", "oos"):
        m = card["metrics"][split_name]
        print(f"[RESEARCH_RUN] {split_name.upper():3} n={m['trades']:4d} "
              f"exp={m['expectancy']:+.3f}R totR={m['total_r']:+7.1f} "
              f"PF={m['profit_factor']:.2f} maxDD={m['max_drawdown_r']:.1f}R")
    print(f"[RESEARCH_RUN] wrote {run_dir}/run.json + signals.jsonl")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run a strategy through the research kernel (kernel_replay) over "
                    "CSV or lake data; resolve signals via the validated backtest math "
                    "and write a reproducible run-card."
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="path to a CSV (MT5 tab export or comma datetime CSV)")
    src.add_argument("--lake-symbol", help="load this symbol from the research lake")
    p.add_argument("--symbol",
                    help="symbol for --csv (used for specs lookup + run-card naming); "
                         "inferred from a SYMBOL_TF.csv filename if omitted")
    p.add_argument("--tf", required=True, choices=_TF_CHOICES, default="H1",
                   help="timeframe (H1 only; other timeframes not yet supported)")
    p.add_argument("--strategy", required=True, help="manifest id under config/manifests/")
    p.add_argument("--split", type=float, default=0.7, help="chronological IS/OOS train fraction")
    p.add_argument("--spread-pips", type=float, default=0.0,
                   help="round-trip spread in broker ticks, charged as a flat cost")
    p.add_argument("--out", default="data/results")
    p.add_argument("--broker", default="fbs")
    p.add_argument("--lake-root", default="data/lake")
    p.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    p.add_argument("--manifest-dir", default=DEFAULT_MANIFEST_DIR)
    p.add_argument("--specs", default=DEFAULT_SPECS_PATH)
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    config = _load_config(args.config)

    try:
        strategy, manifest = _build_strategy(args.strategy, config, args.manifest_dir)
    except Exception as e:  # noqa: BLE001 - CLI boundary, report and exit
        print(f"[RESEARCH_RUN] ERROR: {e}")
        return 1

    if args.lake_symbol:
        symbol = args.lake_symbol
        try:
            df_h1, source = _load_lake_h1(args.lake_root, args.broker, symbol, args.tf)
        except LakeError as e:
            print(f"[RESEARCH_RUN] ERROR: {e}")
            return 1
        data_sha = _sha256_bytes(df_h1.to_csv(index=False).encode())
    else:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"[RESEARCH_RUN] ERROR: csv not found: {csv_path}")
            return 1
        symbol = args.symbol
        if not symbol:
            inferred = infer_symbol_tf(csv_path)
            symbol = inferred[0] if inferred else None
        if not symbol:
            print(f"[RESEARCH_RUN] ERROR: --symbol is required for {csv_path} "
                  f"(filename doesn't match the SYMBOL_TF.csv convention)")
            return 1
        try:
            df_h1 = _load_csv_h1(csv_path, args.tf)
        except Exception as e:  # noqa: BLE001 - CLI boundary, report and exit
            print(f"[RESEARCH_RUN] ERROR: failed to load {csv_path}: {e}")
            return 1
        source = str(csv_path)
        data_sha = _sha256_bytes(csv_path.read_bytes())

    records = replay(df_h1, symbol, [strategy], config, window=300, start=60)
    n_signals = sum(1 for r in records if r["signal"] is not None)

    specs = _load_specs(args.specs)
    spec = specs.get(symbol, _DEFAULT_SPEC)
    spec_source = "data/specs.json" if symbol in specs else "default"
    risk_cfg = config.get("risk", {}).get("trade", {})
    commission_per_lot = float(risk_cfg.get("static_commission_usd", 7.0))
    max_lots = float(risk_cfg.get("hard_max_lots", 5.0))

    trades, skipped = _signals_to_trades(records, df_h1, args.spread_pips, spec,
                                          commission_per_lot, max_lots)
    n_trades = sum(1 for t in trades if t["filled"])

    is_trades, oos_trades = bt.split_trades(trades, train_frac=args.split)
    metrics_is = bt.aggregate_metrics(is_trades)
    metrics_oos = bt.aggregate_metrics(oos_trades)

    config_hash = _sha256_bytes(
        json.dumps(config.get("strategies", {}).get(args.strategy, {}), sort_keys=True).encode()
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out) / f"{ts}_{args.strategy}_{symbol}_{args.tf}"
    run_dir.mkdir(parents=True, exist_ok=True)

    card = {
        "git_sha": _git_sha(),
        "strategy": {"id": manifest.id, "version": manifest.version},
        "config_hash": config_hash,
        "data": {"source": source, "sha256": data_sha},
        "n_bars": int(len(df_h1)),
        "n_signals": n_signals,
        "n_trades": n_trades,
        "n_skipped_busy": len(skipped),
        "split": args.split,
        "metrics": {"is": metrics_is, "oos": metrics_oos},
        "spread_assumption": {
            "spread_pips": args.spread_pips,
            "cost_model": "trade_dollars",
            "commission_per_lot": commission_per_lot,
            "risk_dollars": DEFAULT_RISK_DOLLARS,
            "max_lots": max_lots,
            "tick_size": spec.get("tick_size"),
            "tick_value": spec.get("tick_value"),
            "vol_step": spec.get("vol_step"),
            "spec_source": spec_source,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    (run_dir / "run.json").write_text(json.dumps(card, indent=2, sort_keys=True))
    with open(run_dir / "signals.jsonl", "w") as f:
        for t in sorted(trades + skipped, key=lambda t: t["bar_idx"]):
            f.write(json.dumps(t, default=str) + "\n")

    _print_report(card, run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
# Plan 07 / Task 10 driver: 11 pooled gate runs (defaults, x1.5 stress,
# baseline, 8 one-at-a-time +-30% sweeps). Each run ~1.5-3h (9 symbols x
# ~20k-bar kernel replay); run under nohup, sequentially.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"   # override for worktrees: PY=/abs/path/to/python
SYMS="EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,GBPJPY,XAUUSD,US30,BTCUSD"
OUT=data/results/gyro_gate
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

run() {
  echo "=== [$(date -u +%H:%M:%S)] research_run $* ==="
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] $PY scripts/research_run.py --lake-symbols \"$SYMS\" --tf H1 --split 0.7 --set signal_grading.min_grade=C --out \"$OUT\" $*"
    return 0
  fi
  $PY scripts/research_run.py --lake-symbols "$SYMS" --tf H1 --split 0.7 \
      --set signal_grading.min_grade=C --out "$OUT" "$@"
}

run --strategy gyroscope --spread-mult 1.0                       # 1 defaults (headline)
run --strategy gyroscope --spread-mult 1.5                       # 2 stress (criterion 7)
run --strategy ma_slope_baseline --spread-mult 1.0               # 3 baseline (criterion 6)
for kv in sprt.alpha=0.035 sprt.alpha=0.065 sprt.beta=0.14 sprt.beta=0.26 \
          sprt.delta=0.28 sprt.delta=0.52 q_atr_frac=0.035 q_atr_frac=0.065; do
  run --strategy gyroscope --spread-mult 1.0 \
      --set "strategies.gyroscope.$kv"                           # 4-11 sweeps (criterion 5)
done
echo "=== GATE RUNS COMPLETE ==="

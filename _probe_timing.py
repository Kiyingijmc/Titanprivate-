"""Scratch probe: run the unit suite per-module, streaming wall time. Not committed."""
import os
import subprocess
import sys
import time

PY = "/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python"

mods = sorted(
    f[:-3] for f in os.listdir("tests/unit") if f.startswith("test_") and f.endswith(".py")
)

rows = []
for m in mods:
    t0 = time.perf_counter()
    p = subprocess.run(
        [PY, "-m", "unittest", f"tests.unit.{m}"],
        capture_output=True,
        text=True,
    )
    dt = time.perf_counter() - t0
    tail = p.stderr.strip().splitlines()
    status = tail[-1] if tail else "?"
    rows.append((dt, m, p.returncode))
    print(f"{dt:8.2f}s  rc={p.returncode}  {m}  | {status}", flush=True)

print("\n==== SLOWEST ====", flush=True)
for dt, m, rc in sorted(rows, reverse=True)[:40]:
    print(f"{dt:8.2f}s  rc={rc}  {m}", flush=True)
print(f"==== total {sum(r[0] for r in rows):.1f}s over {len(rows)} modules ====", flush=True)
bad = [(m, rc) for _, m, rc in rows if rc != 0]
print(f"==== FAILING MODULES: {bad} ====", flush=True)

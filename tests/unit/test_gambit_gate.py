# tests/unit/test_gambit_gate.py
# Gate math on hand-built fixtures — thresholds are pre-registered constants.
import unittest
import pandas as pd

from scripts.gambit_gate import (
    KILL_MIN_N, evaluate_kill, evaluate_gate, add_net, split_is_oos)


def frame(n, sym="US30", net=0.5, t0="2024-01-01"):
    times = pd.date_range(t0, periods=n, freq="6h")
    return pd.DataFrame({
        "sym": [sym] * n, "setup": ["judas"] * n, "session": ["ny_am"] * n,
        "time": times.astype(str), "dir": ["SELL"] * n,
        # risk deliberately LARGE (100 price units) so real US30/XAUUSD spec
        # costs stay far below the 0.25R sanity bound — these tests exercise
        # criterion logic, not cost economics.
        "entry": 100.0, "sl": 200.0, "tp": -100.0, "risk": 100.0,
        "outcome": ["TP"] * n, "gross_r": [net] * n, "managed_r": [net] * n,
    })


class TestGate(unittest.TestCase):
    def test_insufficient_n(self):
        out = evaluate_kill(add_net(frame(KILL_MIN_N - 1), 1.0), "managed")
        self.assertEqual(out["verdict"], "INSUFFICIENT-N")

    def test_kill_pass_on_strong_positive(self):
        out = evaluate_kill(add_net(frame(200, net=0.5), 1.0), "managed")
        self.assertEqual(out["verdict"], "PASS")
        self.assertGreater(out["ci_lo"], 0.0)

    def test_kill_fail_on_negative(self):
        out = evaluate_kill(add_net(frame(200, net=-0.3), 1.0), "managed")
        self.assertEqual(out["verdict"], "FAIL")

    def test_is_oos_split_is_chronological_per_symbol(self):
        df = add_net(pd.concat([frame(100, sym="US30"),
                                frame(100, sym="XAUUSD")]), 1.0)
        is_df, oos_df = split_is_oos(df)
        for sym in ("US30", "XAUUSD"):
            a = is_df[is_df["sym"] == sym]["time"].max()
            b = oos_df[oos_df["sym"] == sym]["time"].min()
            self.assertLess(a, b)
            self.assertEqual(len(is_df[is_df["sym"] == sym]), 70)

    def test_gate_all_criteria_reported(self):
        df = add_net(frame(400, net=0.5), 1.0)
        out = evaluate_gate(df, sweep_dfs=[df, df, df, df])
        self.assertEqual(sorted(out["criteria"].keys()),
                         ["breadth", "calibration", "confidence", "cost",
                          "economics", "robustness", "stress"])
        self.assertIn(out["verdict"], ("GO", "NO-GO"))

    def test_stress_criterion_uses_the_gate_exit_model(self):
        # managed_r and gross_r deliberately diverge in sign so the stress
        # criterion's basis is observable: under exit_model="fixed" (net_r
        # built from gross_r), stress at 1.5x must come out negative even
        # though the managed_r basis would be positive. If evaluate_gate's
        # internal stress re-net ever drops exit_model and silently falls
        # back to "managed", this flips to True and the test catches it.
        n = 200
        times = pd.date_range("2024-01-01", periods=n, freq="6h")
        raw = pd.DataFrame({
            "sym": ["US30"] * n, "setup": ["judas"] * n,
            "session": ["ny_am"] * n, "time": times.astype(str),
            "dir": ["SELL"] * n, "entry": 100.0, "sl": 200.0, "tp": -100.0,
            "risk": 100.0, "outcome": ["TP"] * n,
            "gross_r": [-0.5] * n, "managed_r": [0.5] * n,
        })
        df = add_net(raw, 1.0, "fixed")
        out = evaluate_gate(df, sweep_dfs=[df, df, df, df],
                             exit_model="fixed")
        self.assertFalse(out["criteria"]["stress"])
        self.assertEqual(out["exit_model"], "fixed")


if __name__ == "__main__":
    unittest.main()

import json, tempfile, unittest
from pathlib import Path
from src.ops.jsonlog import JsonLogger

class TestJsonLogger(unittest.TestCase):
    def test_writes_one_json_line_with_schema(self):
        with tempfile.TemporaryDirectory() as d:
            jl = JsonLogger(d)
            jl.log("INFO", "core", "boot", msg="hello", answer=42)
            files = list(Path(d).glob("titan-*.jsonl"))
            self.assertEqual(len(files), 1)
            rec = json.loads(files[0].read_text().strip())
            for key in ("ts", "level", "domain", "event", "msg"):
                self.assertIn(key, rec)
            self.assertEqual(rec["answer"], 42)
            self.assertEqual(rec["event"], "boot")

    def test_bind_merges_context(self):
        with tempfile.TemporaryDirectory() as d:
            jl = JsonLogger(d)
            child = jl.bind(bar_cycle_id="EURUSD:H1:t0")
            child.log("INFO", "bus", "publish")
            rec = json.loads(next(Path(d).glob("*.jsonl")).read_text().strip())
            self.assertEqual(rec["bar_cycle_id"], "EURUSD:H1:t0")

    def test_unserializable_field_never_raises(self):
        with tempfile.TemporaryDirectory() as d:
            jl = JsonLogger(d)
            jl.log("INFO", "x", "y", weird=object())  # must not raise
            self.assertEqual(jl.drops, 0)  # coerced via default=str, not dropped

if __name__ == "__main__":
    unittest.main()

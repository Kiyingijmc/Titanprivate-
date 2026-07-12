import os
import tempfile
import unittest

import yaml

from src.strategies.manifest import ManifestError, StrategyManifest, load_manifest, load_manifests


def _write_yaml(dir_path, filename, data):
    path = os.path.join(dir_path, filename)
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


def _valid_data(**overrides):
    data = {
        "id": "test_strategy",
        "version": "1.0.0",
        "class_path": "src.strategies.models.foo:Foo",
        "family": "smc",
        "timeframe": "H1",
        "requires": ["smc.enriched_df", "smc.bias_context"],
        "status": "live",
        "priority": 42,
    }
    data.update(overrides)
    return data


class TestLoadManifest(unittest.TestCase):
    def test_happy_path_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, "test_strategy.yaml", _valid_data())
            manifest = load_manifest(path)
            self.assertIsInstance(manifest, StrategyManifest)
            self.assertEqual(manifest.id, "test_strategy")
            self.assertEqual(manifest.version, "1.0.0")
            self.assertEqual(manifest.class_path, "src.strategies.models.foo:Foo")
            self.assertEqual(manifest.family, "smc")
            self.assertEqual(manifest.timeframe, "H1")
            self.assertEqual(manifest.requires, ("smc.enriched_df", "smc.bias_context"))
            self.assertIsInstance(manifest.requires, tuple)
            self.assertEqual(manifest.status, "live")
            self.assertEqual(manifest.priority, 42)

    def test_bad_status_and_bad_timeframe_raise(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, "bad_status.yaml", _valid_data(status="bogus"))
            with self.assertRaises(ManifestError) as ctx:
                load_manifest(path)
            self.assertIn("status", str(ctx.exception))
            self.assertIn("bad_status.yaml", str(ctx.exception))

        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, "bad_tf.yaml", _valid_data(timeframe="M1"))
            with self.assertRaises(ManifestError) as ctx:
                load_manifest(path)
            self.assertIn("timeframe", str(ctx.exception))

    def test_missing_id_raises(self):
        with tempfile.TemporaryDirectory() as d:
            data = _valid_data()
            del data["id"]
            path = _write_yaml(d, "missing_id.yaml", data)
            with self.assertRaises(ManifestError) as ctx:
                load_manifest(path)
            self.assertIn("id", str(ctx.exception))

    def test_malformed_class_path_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, "bad_class_path.yaml", _valid_data(class_path="no_colon_here"))
            with self.assertRaises(ManifestError) as ctx:
                load_manifest(path)
            self.assertIn("class_path", str(ctx.exception))

    def test_non_dict_root_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scalar_root.yaml")
            with open(path, "w") as f:
                f.write("42\n")
            with self.assertRaises(ManifestError) as ctx:
                load_manifest(path)
            msg = str(ctx.exception)
            self.assertIn("scalar_root.yaml", msg)
            self.assertIn("mapping", msg)

    def test_non_string_requires_entry_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, "bad_requires.yaml", _valid_data(requires=["ok", 42]))
            with self.assertRaises(ManifestError) as ctx:
                load_manifest(path)
            self.assertIn("requires", str(ctx.exception))

    def test_class_path_two_colons_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_yaml(d, "two_colons.yaml", _valid_data(class_path="a:b:c"))
            with self.assertRaises(ManifestError) as ctx:
                load_manifest(path)
            self.assertIn("class_path", str(ctx.exception))


class TestLoadManifests(unittest.TestCase):
    def test_sorted_loading_and_duplicate_id_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            _write_yaml(d, "b_second.yaml", _valid_data(id="second"))
            _write_yaml(d, "a_first.yaml", _valid_data(id="first"))
            manifests = load_manifests(d)
            self.assertEqual([m.id for m in manifests], ["first", "second"])

        with tempfile.TemporaryDirectory() as d:
            _write_yaml(d, "a.yaml", _valid_data(id="dup"))
            _write_yaml(d, "b.yaml", _valid_data(id="dup"))
            with self.assertRaises(ManifestError) as ctx:
                load_manifests(d)
            self.assertIn("dup", str(ctx.exception))


class TestRealSilverBulletManifest(unittest.TestCase):
    def test_real_manifest_loads(self):
        path = os.path.join("config", "manifests", "silver_bullet.yaml")
        manifest = load_manifest(path)
        self.assertEqual(manifest.id, "silver_bullet")
        self.assertEqual(manifest.status, "live")


if __name__ == "__main__":
    unittest.main()

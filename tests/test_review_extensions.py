"""AI-generated integration checks for portable reports and evidence boundaries."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import build_review as review
import review_data


class ReportExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(SKILL / "examples/review", self.root / "inputs")
        self.manifest = self.root / "inputs/report.json"
        self.spec = json.loads(self.manifest.read_text())
        self.out = self.root / "output"

    def write(self):
        self.manifest.write_text(json.dumps(self.spec))

    def test_baseline_and_progress_use_recorded_series(self):
        model, _, _ = review_data.load(self.manifest)
        self.assertEqual(
            model["baselines"][0]["series"]["statistics"]["wall_s"]["median"], 21
        )
        history = model["progress"]["historical"][0]
        self.assertEqual(history["kind"], "historical_unpaired")
        self.assertNotIn("pair_ids", history)
        self.assertNotIn("paired_saving_s", history)
        self.assertEqual(history["before"]["statistics"]["n"], 3)
        self.assertEqual(history["after"]["statistics"]["median"], 9)
        self.assertEqual(model["progress"]["totals"], ["combined"])

    def test_total_is_measured_comparison_not_sum(self):
        model, _, _ = review_data.load(self.manifest)
        results = {c["id"]: c["statistics"] for c in model["comparisons"]}
        self.assertEqual(results["combined"]["paired_saving_s"]["median"], 7)
        self.assertNotEqual(
            results["combined"]["paired_saving_s"]["median"],
            results["cache"]["paired_saving_s"]["median"],
        )
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn("Directly measured cumulative comparisons", page)
        self.assertIn("Historical endpoints — unpaired", page)

    def test_unknown_and_duplicate_summary_references_fail_before_output(self):
        for progress in [
            dict(note="test", selected=["missing"]),
            dict(note="test", totals=["cache", "cache"]),
            dict(note="test", totals=[[]]),
            dict(
                note="test",
                historical=[
                    dict(
                        title="x",
                        note="x",
                        **{
                            "from": {"baseline": "original"},
                            "to": {"comparison": "cache", "side": "invalid"},
                        }
                    )
                ],
            ),
        ]:
            with self.subTest(progress=progress):
                self.spec["progress"] = progress
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                self.assertFalse(self.out.exists())

    def test_history_cannot_mix_public_and_nested_boundaries(self):
        for key, value in [("boundary", "one Lean module"), ("command", "lean --run")]:
            with self.subTest(key=key):
                item = self.spec["comparisons"][0]
                original = item[key]
                item[key] = value
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                item[key] = original
                self.assertFalse(self.out.exists())

    def test_ids_cannot_duplicate_or_capture_ui_controls(self):
        for invalid in ["original", "measurements", "frame-viewer", "<script>"]:
            with self.subTest(invalid=invalid):
                self.spec["comparisons"][0]["id"] = invalid
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)

    def test_profile_attachment_must_name_a_comparison(self):
        self.spec["profiles"][0]["comparison"] = "missing"
        self.write()
        with self.assertRaises(ValueError):
            review.build(self.manifest, self.out)
        self.assertFalse(self.out.exists())

    def test_resources_are_separate_medians_and_preserved(self):
        model, _, _ = review_data.load(self.manifest)
        s = model["baselines"][0]["series"]["statistics"]
        self.assertEqual(s["user_s"]["median"], 10.5)
        self.assertEqual(s["peak_rss_kib"]["median"], 1024)
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn("peak RSS (KiB)", page)
        self.assertEqual(
            (self.out / "baseline-00.csv").read_bytes(),
            (self.root / "inputs/baseline.csv").read_bytes(),
        )

    def test_bad_resource_or_missing_inclusion_flag_is_not_silently_ignored(self):
        source = self.root / "inputs/baseline.csv"
        original = source.read_text()
        for bad in [
            original.replace("1024", "nan"),
            original.replace("true", "TRUE"),
            original.replace("validated", "unknown"),
        ]:
            source.write_text(bad)
            with self.assertRaises(ValueError):
                review.build(self.manifest, self.out)
            self.assertFalse(self.out.exists())

    def test_csv_duplicate_headers_and_extra_cells_fail(self):
        source = self.root / "inputs/baseline.csv"
        original = source.read_text()
        for bad in [
            original.replace("system_s", "user_s"),
            original + "original,1,2,0,measured,true,true,,1,0,1,extra\n",
        ]:
            source.write_text(bad)
            with self.assertRaises(ValueError):
                review.build(self.manifest, self.out)

    def test_single_observation_quartiles_and_overflow(self):
        self.assertEqual(
            review.stats([2]), dict(n=1, median=2, q1=2, q3=2, iqr=0, min=2, max=2)
        )
        for values in ([], [float("nan")], [1e308, 1e308]):
            with self.assertRaises(ValueError):
                review.stats(values)
        with self.assertRaises(ValueError):
            review_data.reduction(1e-300, 1e300)

    def test_invalid_json_types_and_constants_fail_before_output(self):
        for key, value in [
            ("profiles", {}),
            ("progress", []),
            ("baselines", [None]),
            ("attribution", ["bad"]),
            ("progress", {"note": "test", "historical": [None]}),
        ]:
            with self.subTest(key=key):
                original = copy.deepcopy(self.spec)
                self.spec[key] = value
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                self.spec = original
                self.assertFalse(self.out.exists())
        for raw in [
            '{"schema":"lean-profile-review-v1","extra":NaN}',
            '{"schema":"lean-profile-review-v1","extra":1e400}',
            '{"schema":"a","schema":"b"}',
        ]:
            self.manifest.write_text(raw)
            with self.assertRaises(ValueError):
                review.build(self.manifest, self.out)

    def test_csv_copy_and_hash_share_one_snapshot(self):
        original_load = review.load
        source = self.root / "inputs/comparison.csv"
        before = source.read_bytes()

        def mutate_after_capture(path):
            result = original_load(path)
            source.write_bytes(b"changed after capture")
            return result

        with patch.object(review, "load", side_effect=mutate_after_capture):
            review.build(self.manifest, self.out)
        self.assertEqual((self.out / "samples-00.csv").read_bytes(), before)
        data = json.loads((self.out / "review-data.json").read_text())
        self.assertEqual(
            data["comparisons"][0]["samples_sha256"], hashlib.sha256(before).hexdigest()
        )

    def test_profile_only_report_needs_no_comparison_filter(self):
        self.spec.pop("progress")
        self.spec.pop("comparisons")
        self.spec.pop("baselines")
        self.write()
        page = review.build(self.manifest, self.out).read_text()
        self.assertNotIn('id="filter"', page)
        self.assertIn("data-perfetto=", page)

    def test_viewer_is_lazy_and_text_is_escaped(self):
        viewer = self.root / "inputs/viewer #1.html"
        viewer.write_text("<!doctype html><title>Fixture</title>")
        self.spec["profiles"][0].update(
            kind="viewer",
            path=viewer.name,
            note="<img src=x onerror=bad()>",
            comparison="cache",
        )
        self.write()
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn('data-source="../inputs/viewer%20%231.html"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertNotIn("onerror=bad()>", page)
        self.assertIn("&lt;img", page)

    @unittest.skipUnless(
        importlib.util.find_spec("matplotlib"), "optional Matplotlib not installed"
    )
    def test_plot_files_retain_input_ids_and_hashes(self):
        review.build(self.manifest, self.out, plots=True)
        model = json.loads((self.out / "review-data.json").read_text())
        self.assertEqual(len(model["figures"]), 6)
        for f in model["figures"]:
            path = self.out / f["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), f["sha256"])
            self.assertTrue(f["source_ids"])


if __name__ == "__main__":
    unittest.main()

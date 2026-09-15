"""Shared datasets, outcome presentation, history and optional plot integration."""

import copy
import csv
import hashlib
import html
import importlib.util
import io
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
from review_observations import observations
from review_helpers import paired_rows


class ReportExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(SKILL / "examples/review", self.root / "inputs")
        self.manifest = self.root / "inputs/report.json"
        self.spec = json.loads(self.manifest.read_text())
        self.out = self.root / "report"

    def write(self):
        self.manifest.write_text(json.dumps(self.spec))

    def test_baseline_and_history_are_recorded_series_not_synthetic_pairs(self):
        model, _, _ = review_data.load(self.manifest)
        self.assertEqual(model["baselines"][0]["series"]["statistics"]["wall_s"]["median"], 21)
        history = model["progress"]["historical"][0]
        self.assertEqual(history["kind"], "historical_unpaired")
        self.assertNotIn("pair_ids", history)
        self.assertNotIn("paired_saving_s", history)
        self.assertEqual(history["before"]["statistics"]["n"], 3)
        self.assertEqual(history["after"]["statistics"]["median"], 9)

    def test_total_is_an_actual_contrast_not_composed(self):
        model, _, _ = review_data.load(self.manifest)
        results = {c["id"]: c["statistics"] for c in model["comparisons"]}
        self.assertEqual(results["combined"]["paired_saving_s"]["median"], 7)
        self.assertNotEqual(results["combined"]["paired_saving_s"]["median"],
                            results["cache"]["paired_saving_s"]["median"])
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn("Directly measured cumulative comparisons", page)
        self.assertIn("Historical endpoints — unpaired", page)
        self.assertEqual(page.count(html.escape(self.spec["progress"]["note"])), 1)

    def test_three_way_dataset_is_copied_and_read_once_for_all_consumers(self):
        source = self.root / "inputs/three-way.jsonl"
        original_read = Path.read_bytes
        reads = []

        def counted(path):
            if path == source:
                reads.append(path)
            return original_read(path)

        with patch.object(Path, "read_bytes", counted):
            page = review.build(self.manifest, self.out).read_text()
        self.assertEqual(reads, [source])
        self.assertEqual(len(list(self.out.glob("*.jsonl"))), 1)
        self.assertEqual((self.out / "dataset-03.jsonl").read_bytes(), source.read_bytes())
        self.assertIn("Multi-configuration overview", page)
        self.assertIn("Current versus reference", page)
        self.assertIn("Warmup-only timeout", page)

    def test_contrasts_reuse_the_dataset_series(self):
        with patch.object(review_data, "series", wraps=review_data.series) as summarize:
            model, _, _ = review_data.load(self.manifest)
        self.assertEqual(summarize.call_count, sum(len(d["configurations"]) for d in model["datasets"]))
        datasets = {d["id"]: d for d in model["datasets"]}
        for contrast in model["comparisons"]:
            for side in ("control", "candidate"):
                self.assertIs(contrast["statistics"]["series"][side],
                              datasets[contrast["dataset"]]["series"][contrast[side]])

    def test_artifact_hash_cache_spans_profiles_and_links_but_not_builds(self):
        source = self.root / "inputs/trace.json"
        self.spec["links"] = [dict(title="Trace", path="trace.json")] * 2
        self.write()
        with patch.object(review_data, "digest", wraps=review_data.digest) as hashes:
            first, _, _ = review_data.load(self.manifest)
            self.assertEqual(sum(call.args[0] == source for call in hashes.call_args_list), 1)
        self.assertEqual(len(first["links"]), 1)
        source.write_text('{"traceEvents":[],"changed":true}')
        second, _, _ = review_data.load(self.manifest)
        self.assertNotEqual(first["links"][0]["sha256"], second["links"][0]["sha256"])

    def test_timeout_baseline_has_no_fabricated_median_or_speedup(self):
        model, _, _ = review_data.load(self.manifest)
        baseline = model["baselines"][1]["series"]
        self.assertEqual(baseline["statistics"], {})
        self.assertFalse(baseline["censored"])
        contrast = model["comparisons"][-1]["statistics"]
        self.assertIsNone(contrast["paired_saving_s"])
        self.assertIsNone(contrast["median_reduction_pct"])
        self.spec["progress"]["totals"].append("timeout-contrast")
        self.write()
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn("warmup: 1 timeout; timeout limits 60 s", page)
        self.assertIn("Not estimated", page)

    def test_history_with_missing_baseline_stays_unestimated(self):
        # Match declared metadata to inspect the no-completion case, not reject
        # mismatched command/boundary first.
        for key in review_data.METADATA:
            self.spec["datasets"][3][key] = self.spec["datasets"][0][key]
        self.spec["progress"]["historical"][0]["from"] = {"baseline": "stalled-warmup"}
        self.write()
        model, _, _ = review_data.load(self.manifest)
        self.assertIsNone(model["progress"]["historical"][0]["median_reduction_pct"])
        self.assertIn("Not estimated", review.build(self.manifest, self.out).read_text())

    def test_unknown_duplicate_and_malformed_references_fail(self):
        changes = [
            dict(note="test", selected=["missing"]),
            dict(note="test", totals=["cache", "cache"]),
            dict(note="test", totals=[[]]),
            dict(note="test", historical=[dict(title="x", note="x",
                 **{"from": {"baseline": "original"},
                    "to": {"comparison": "cache", "side": "invalid"}})]),
        ]
        for progress in changes:
            with self.subTest(progress=progress):
                self.spec["progress"] = progress
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                self.assertFalse(self.out.exists())

    def test_history_does_not_mix_commands_or_boundaries(self):
        for key in ("boundary", "command"):
            with self.subTest(key=key):
                original = self.spec["datasets"][1][key]
                self.spec["datasets"][1][key] = "nested diagnostic"
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                self.spec["datasets"][1][key] = original

    def test_ids_do_not_capture_ui_controls_or_each_other(self):
        for invalid in ("original", "datasets", "decision-filter", "frame-viewer", "group-experiment", "<script>"):
            with self.subTest(invalid=invalid):
                self.spec["comparisons"][0]["id"] = invalid
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)

    def test_resources_keep_distinct_units_and_population(self):
        model, _, _ = review_data.load(self.manifest)
        s = model["baselines"][0]["series"]["statistics"]
        self.assertEqual(s["user_s"]["median"], 10.5)
        self.assertEqual(s["peak_rss_kib"]["median"], 1024)
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn("peak RSS (KiB)", page)

    def test_malformed_csv_columns_and_resources_fail_before_output(self):
        source = self.root / "inputs/baseline.csv"
        original = source.read_text()
        for bad in (original.replace("1024", "nan"), original.replace("included", "accepted"),
                    original.replace("system_s", "user_s"), original.replace(",true,", ",TRUE,"),
                    original + "extra,cells\n", original + '"unterminated field'):
            with self.subTest(bad=bad):
                source.write_text(bad)
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                self.assertFalse(self.out.exists())

    def test_invalid_json_types_and_constants_fail_before_output(self):
        for key, value in [("profiles", {}), ("progress", []), ("baselines", [None]),
                           ("datasets", [None]), ("attribution", ["bad"]),
                           ("progress", {"note": "x", "historical": [None]})]:
            with self.subTest(key=key):
                original = copy.deepcopy(self.spec)
                self.spec[key] = value
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                self.spec = original
                self.assertFalse(self.out.exists())
        for raw in ('{"schema":"x","extra":NaN}', '{"schema":"x","extra":1e400}',
                    '{"schema":"a","schema":"b"}'):
            self.manifest.write_text(raw)
            with self.assertRaises(ValueError):
                review.build(self.manifest, self.out)

    def test_statistics_hash_and_archive_use_exact_single_read_snapshot(self):
        source = self.root / "inputs/comparison.csv"
        before = source.read_bytes()
        original_parse = review_data.observations
        original_read = Path.read_bytes
        reads = []

        def counted(path):
            if path == source:
                reads.append(path)
            return original_read(path)

        def mutate(snapshot, configurations, source_name="observations", **kwargs):
            result = original_parse(snapshot, configurations, source_name, **kwargs)
            if Path(source_name) == source:
                rows = list(csv.DictReader(io.StringIO(snapshot.decode())))
                with source.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(row | {"wall_s": "100"} for row in rows)
            return result

        with patch.object(Path, "read_bytes", counted), patch.object(review_data, "observations", mutate):
            review.build(self.manifest, self.out)
        self.assertEqual(reads, [source])
        archived_raw = (self.out / "dataset-01.csv").read_bytes()
        self.assertEqual(archived_raw, before)
        data = json.loads((self.out / "review-data.json").read_text())
        record = data["comparisons"][0]
        self.assertEqual(record["samples_sha256"], hashlib.sha256(before).hexdigest())
        archived = paired_rows(observations(archived_raw, ["control", "candidate"]), "control", "candidate")
        for key in ("control", "candidate", "paired_saving_s"):
            self.assertEqual(record["statistics"][key], archived[key])
        self.assertEqual(record["statistics"]["control"]["median"], 11)
        changed = paired_rows(observations(source.read_bytes(), ["control", "candidate"]), "control", "candidate")
        self.assertEqual(changed["control"]["median"], 100)

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "optional Matplotlib not installed")
    def test_plots_preserve_sources_hashes_and_small_time_units(self):
        review.build(self.manifest, self.out, plots=True)
        model = json.loads((self.out / "review-data.json").read_text())
        self.assertEqual(len(model["figures"]), 2 * (1 + len(model["comparisons"])))
        for figure in model["figures"]:
            path = self.out / figure["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), figure["sha256"])
            self.assertTrue(figure["source_ids"])
        svg = (self.out / "figures/native-contrast.svg").read_text()
        self.assertIn("wall time (ms)", svg.lower())
        self.assertIn("Paired saving (µs)", svg)
        self.assertIn("No included completion", (self.out / "figures/baselines.svg").read_text())


if __name__ == "__main__":
    unittest.main()

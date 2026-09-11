"""Retained command capture import: provenance is not output validation."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import import_comparison as importer
import review_data
from build_review import build
from review_data import load
from review_helpers import jsonl


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        self.out = self.root / "imported"
        self.commands = {name: dict(argv=["never-execute", name, "arg with spaces"])
                         for name in ("baseline", "candidate")}
        self.manifest = dict(schema="lean-profile-compare-alpha", commands=self.commands,
                             expected_exit_code=0, timeout_seconds=60, perf=None)
        self.rows = [dict(sequence=i, phase="measured", **{"pass": 1}, slot=i,
                          label=name, argv=self.commands[name]["argv"], elapsed_ns=2**53+i,
                          exit_code=0, timed_out=False, interrupted=False,
                          launch_error=None, evidence_error=None,
                          stdout=f"stdout/{i}.txt", stderr=f"stderr/{i}.txt")
                     for i, name in enumerate(self.commands, 1)]
        self.identity = dict(schema="lean-profile-identity-check-alpha", valid=True, changes=[])
        self.save()

    def save(self):
        (self.capture / "manifest.json").write_text(json.dumps(self.manifest))
        (self.capture / "runs.jsonl").write_bytes(jsonl(self.rows))
        (self.capture / "identity-check.json").write_text(json.dumps(self.identity))

    def validation(self):
        artifact = self.root / "validation-results.json"
        artifact.write_text(json.dumps({str(r["sequence"]): "correct" for r in self.rows}))
        spec = dict(
            schema="lean-profile-command-validation-alpha",
            runs_sha256=hashlib.sha256((self.capture / "runs.jsonl").read_bytes()).hexdigest(),
            manifest_sha256=hashlib.sha256((self.capture / "manifest.json").read_bytes()).hexdigest(),
            checks=[dict(sequence=r["sequence"], result="passed", scope="Fixture correctness check",
                         artifacts=[dict(path=artifact.name, sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                                         record=f'/{r["sequence"]}')]) for r in self.rows],
        )
        path = self.root / "validation.json"
        path.write_text(json.dumps(spec))
        return path, spec

    def run_import(self, validation=None):
        return importer.import_comparison(self.capture, self.out, boundary="child invocation plus harness overhead",
                                          cohort="synthetic warm cache", validation=validation)

    def test_no_validation_keeps_completions_visible_but_not_included(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("must not execute")):
            path = self.run_import()
        model, _, _ = load(path)
        self.assertIsNone(model["comparisons"][0]["statistics"]["paired_saving_s"])
        values = model["datasets"][0]["series"]["baseline"]
        self.assertEqual(len(values["outcomes"]), 1)
        self.assertFalse(values["outcomes"][0]["validated"])
        self.assertIn("no output-validation record", values["excluded"][0]["exclude_reason"])
        self.assertIn("No included measured pairs", build(path, self.root / "report").read_text())

    def test_explicit_validation_preserves_clocks_argv_and_snapshots(self):
        validation, _ = self.validation()
        path = self.run_import(validation)
        model, _, _ = load(path)
        stat = model["comparisons"][0]["statistics"]
        self.assertEqual(stat["paired_saving_s"]["n"], 1)
        self.assertIsNone(model["comparisons"][0]["decision_status"])
        row = stat["series"]["control"]["observations"][0]
        self.assertEqual(row["elapsed_ns"], 2**53+1)
        self.assertEqual(row["argv"], self.commands["baseline"]["argv"])
        self.assertEqual(row["capture_directory"], str(self.capture))
        self.assertEqual(row["validation"]["record"], "/checks/0")
        for original, archived in (("runs.jsonl", "source-runs.jsonl"),
                                   ("manifest.json", "source-manifest.json"),
                                   ("identity-check.json", "source-identity.json")):
            self.assertEqual((self.capture / original).read_bytes(), (self.out / archived).read_bytes())
        self.assertEqual(validation.read_bytes(), (self.out / "source-validation.json").read_bytes())
        with self.assertRaises(FileExistsError):
            self.run_import(validation)

    def test_shared_validation_artifact_is_hashed_and_linked_once_per_invocation(self):
        validation, _ = self.validation()
        evidence = self.root / "validation-results.json"
        with mock.patch.object(importer, "digest", wraps=importer.digest) as hashes:
            path = self.run_import(validation)
        self.assertEqual([call.args[0] for call in hashes.call_args_list], [evidence])
        with mock.patch.object(review_data, "digest", wraps=review_data.digest) as hashes:
            model, _, _ = load(path)
        self.assertEqual(sum(call.args[0] == evidence for call in hashes.call_args_list), 1)
        self.assertEqual(sum(link["artifact_path"] == str(evidence) for link in model["links"]), 1)
        records = [b["series"]["observations"][0]["validation"] for b in model["baselines"]]
        self.assertEqual([v["record"] for v in records], ["/checks/0", "/checks/1"])
        self.assertEqual([v["artifacts"][0]["record"] for v in records], ["/1", "/2"])
        # Caches must not survive an invocation or hide a changed artifact.
        evidence.write_text("changed")
        self.out = self.root / "second-import"
        with self.assertRaises(ValueError):
            self.run_import(validation)
        self.assertFalse(self.out.exists())

    def test_repeated_artifact_with_conflicting_hash_is_rejected(self):
        validation, spec = self.validation()
        spec["checks"][1]["artifacts"][0]["sha256"] = "0" * 64
        validation.write_text(json.dumps(spec))
        with self.assertRaises(ValueError):
            self.run_import(validation)
        self.assertFalse(self.out.exists())

    def test_abnormal_measured_outcomes_remain_excluded_with_passed_output_checks(self):
        original = copy.deepcopy(self.rows)
        for outcome, change in (
            ("interrupted", dict(interrupted=True, exit_code=None)),
            ("error", dict(launch_error="OSError: cannot launch", exit_code=None)),
            ("timeout", dict(timed_out=True, exit_code=None, elapsed_ns=60_020_000_000)),
        ):
            with self.subTest(outcome=outcome):
                self.rows = copy.deepcopy(original)
                self.rows[0].update(change)
                self.save()
                validation, _ = self.validation()
                self.out = self.root / outcome
                model, _, _ = load(self.run_import(validation))
                result = model["comparisons"][0]["statistics"]
                row = result["series"]["control"]["outcomes"][0]
                self.assertEqual(row["outcome"], outcome)
                self.assertFalse(row["included"])
                self.assertTrue(row["validated"])
                self.assertIsNone(result["paired_saving_s"])
                self.assertEqual(result["series"]["control"]["censored"], outcome == "timeout")

    def test_malformed_jsonl_identifies_capture_and_line_before_output(self):
        path = self.capture / "runs.jsonl"
        path.write_bytes(jsonl(self.rows) + b"\n{broken json}\n")
        with self.assertRaisesRegex(ValueError, r"runs\.jsonl:4:"):
            self.run_import()
        self.assertFalse(self.out.exists())

    def test_snapshot_survives_source_mutation(self):
        validation, _ = self.validation()
        original = Path.read_bytes
        counts = {}
        def read(path):
            raw = original(path)
            counts[path] = counts.get(path, 0) + 1
            if path == self.capture / "runs.jsonl":
                path.write_bytes(b"replacement after capture\n")
            return raw
        with mock.patch.object(Path, "read_bytes", read):
            path = self.run_import(validation)
        model, _, _ = load(path)
        self.assertEqual(counts[self.capture / "runs.jsonl"], 1)
        self.assertEqual((self.out / "source-runs.jsonl").read_bytes(), jsonl(self.rows))
        self.assertEqual(model["baselines"][0]["series"]["observations"][0]["elapsed_ns"], 2**53+1)

    def test_missing_or_failed_identity_never_includes_validated_runs(self):
        validation, _ = self.validation()
        for identity in (None, dict(self.identity, valid=False, changes=[{"subject": "binary"}])):
            with self.subTest(identity=identity):
                self.out = self.root / ("missing" if identity is None else "changed")
                path = self.capture / "identity-check.json"
                if identity is None:
                    path.unlink()
                else:
                    path.write_text(json.dumps(identity))
                model, _, _ = load(self.run_import(validation))
                row = model["datasets"][0]["series"]["baseline"]["outcomes"][0]
                self.assertTrue(row["validated"])
                self.assertFalse(row["included"])

    def test_timeout_warmup_partial_capture_has_no_measured_baseline(self):
        self.rows = [dict(self.rows[0], phase="warmup", timed_out=True, exit_code=None,
                          elapsed_ns=60_020_000_000)]
        self.save()
        model, _, _ = load(self.run_import())
        baseline = model["baselines"][0]["series"]
        self.assertFalse(baseline["censored"])
        self.assertEqual(baseline["statistics"], {})
        self.assertEqual(baseline["outcomes"][0]["timeout_s"], 60)
        self.assertEqual(baseline["outcomes"][0]["wall_s"], 60.02)
        self.assertEqual(model["baselines"][1]["series"]["outcomes"], [])
        self.assertIsNone(model["comparisons"][0]["statistics"]["median_reduction_pct"])

    def test_nonzero_expected_exit_and_instrumented_scope(self):
        self.manifest.update(expected_exit_code=7, perf={"events": "cycles"})
        for row in self.rows:
            row["exit_code"] = 7
        self.save()
        validation, _ = self.validation()
        model, _, _ = load(self.run_import(validation))
        self.assertEqual(model["comparisons"][0]["statistics"]["control"]["n"], 1)
        self.assertIn("instrumented evidence", model["summary"])

    def test_missing_failed_and_harness_error_checks_exclude_rows(self):
        self.rows[0]["evidence_error"] = "counter file empty"
        self.save()
        validation, spec = self.validation()
        spec["checks"][1]["result"] = "failed"
        validation.write_text(json.dumps(spec))
        model, _, _ = load(self.run_import(validation))
        self.assertIn("harness evidence", model["baselines"][0]["excluded"][0]["exclude_reason"])
        self.assertIn("validation failed", model["baselines"][1]["excluded"][0]["exclude_reason"])
        self.out = self.root / "missing-check"
        spec["checks"] = spec["checks"][:1]
        validation.write_text(json.dumps(spec))
        model, _, _ = load(self.run_import(validation))
        self.assertIn("no output-validation", model["baselines"][1]["excluded"][0]["exclude_reason"])

    def test_validation_binding_evidence_and_ids_fail_before_output(self):
        validation, good = self.validation()
        cases = []
        for key in ("runs_sha256", "manifest_sha256"):
            cases.append(dict(good, **{key: "0"*64}))
        for key, value in (("sequence", 999), ("scope", ""), ("artifacts", []), ("result", "maybe")):
            spec = copy.deepcopy(good)
            spec["checks"][0][key] = value
            cases.append(spec)
        spec = copy.deepcopy(good)
        spec["checks"].append(spec["checks"][0])
        cases.append(spec)
        for key, value in (("path", "missing"), ("sha256", "0"*64), ("record", "")):
            spec = copy.deepcopy(good)
            spec["checks"][0]["artifacts"][0][key] = value
            cases.append(spec)
        for spec in cases:
            with self.subTest(spec=spec):
                validation.write_text(json.dumps(spec))
                with self.assertRaises(ValueError):
                    self.run_import(validation)
                self.assertFalse(self.out.exists())

    def test_malformed_capture_fails_before_output(self):
        original = copy.deepcopy(self.rows)
        cases = [dict(label="wrong"), dict(argv=["different"]), dict(phase=None),
                 dict(elapsed_ns=True), dict(slot=0), dict(sequence=2), dict(exit_code=True),
                 dict(timed_out=1), dict(launch_error=False), dict(evidence_error={})]
        for change in cases:
            with self.subTest(change=change):
                self.rows = copy.deepcopy(original)
                self.rows[0].update(change)
                self.save()
                with self.assertRaises(ValueError):
                    self.run_import()
                self.assertFalse(self.out.exists())
        for commands in ([], {"baseline": []}, {"baseline": {"argv": []}}):
            self.rows = original
            self.manifest["commands"] = commands
            self.save()
            with self.assertRaises(ValueError):
                self.run_import()

    def test_real_harness_capture_imports_without_assuming_correctness(self):
        capture = self.root / "real-capture"
        argv = json.dumps([sys.executable, "-c", "print('synthetic output')"])
        subprocess.run([sys.executable, str(SKILL / "scripts/compare_commands.py"),
                        "--baseline", argv, "--candidate", argv, "--warmups", "0",
                        "--out-dir", str(capture)], cwd=self.root, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.capture = capture
        model, _, _ = load(self.run_import())
        self.assertEqual(len(model["baselines"][0]["series"]["outcomes"]), 2)
        self.assertEqual(model["baselines"][0]["series"]["statistics"], {})

        # Establish actual correctness evidence before exercising the included path.
        self.rows = [json.loads(line) for line in (capture / "runs.jsonl").read_text().splitlines()]
        for row in self.rows:
            self.assertEqual((capture / row["stdout"]).read_bytes(), b"synthetic output\n")
        validation, spec = self.validation()
        for check, row in zip(spec["checks"], self.rows):
            stdout = capture / row["stdout"]
            check.update(scope="Captured stdout equals the expected synthetic output",
                         artifacts=[dict(path=str(stdout), sha256=hashlib.sha256(stdout.read_bytes()).hexdigest(),
                                         record="Entire stdout; checked against b'synthetic output\\n'")])
        validation.write_text(json.dumps(spec))
        self.out = self.root / "validated-import"
        manifest = self.run_import(validation)
        report_dir = self.root / "validated-report"
        page = build(manifest, report_dir)
        model = json.loads((report_dir / "review-data.json").read_text())
        normalized = (self.out / "observations.jsonl").read_bytes()
        self.assertEqual((report_dir / "dataset-00.jsonl").read_bytes(), normalized)
        self.assertEqual(model["datasets"][0]["samples_sha256"], hashlib.sha256(normalized).hexdigest())
        comparison = model["comparisons"][0]["statistics"]
        self.assertEqual(comparison["paired_saving_s"]["n"], 2)
        self.assertEqual(set(comparison["pair_ids"]), {"1", "2"})
        summary = json.loads((capture / "summary.json").read_text())
        for report_saving, harness_saving in zip(comparison["savings"], summary["paired_savings_ns"]):
            self.assertAlmostEqual(report_saving, harness_saving / 1_000_000_000)
        self.assertAlmostEqual(comparison["paired_saving_s"]["median"],
                               summary["paired_saving_median_ns"] / 1_000_000_000)
        self.assertAlmostEqual(comparison["median_reduction_pct"], summary["median_reduction_pct"])
        self.assertIn('href="dataset-00.jsonl"', page.read_text())


if __name__ == "__main__":
    unittest.main()

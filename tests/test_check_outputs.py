import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_outputs as tool


def row(sequence, **overrides):
    return dict(dict(sequence=sequence, stdout=f"stdout/{sequence}.txt", exit_code=0, timed_out=False,
                     interrupted=False, launch_error=None), **overrides)


class CheckOutputsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.capture = self.root / "capture"
        (self.capture / "stdout").mkdir(parents=True)
        (self.capture / "manifest.json").write_text(json.dumps(dict(
            schema="lean-profile-compare-alpha", expected_exit_code=0,
            commands={name: dict(argv=[name]) for name in ("baseline", "candidate")})))
        (self.root / "expected.txt").write_text("ok\n")
        self.out = self.root / "checks" / "validation.json"

    def write(self, rows, outputs):
        (self.capture / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        for sequence, text in outputs.items():
            (self.capture / f"stdout/{sequence}.txt").write_text(text)

    def run_check(self):
        return tool.check_outputs(self.capture, self.root / "expected.txt", "matches trusted run", self.out)

    def test_mismatch_is_recorded_failed_and_unfinished_runs_get_no_check(self):
        self.write([row(1), row(2), row(3, timed_out=True, exit_code=None)], {1: "ok\n", 2: "bad\n"})
        self.assertEqual(self.run_check(), (1, 2))
        spec = json.loads(self.out.read_text())
        self.assertEqual([c["result"] for c in spec["checks"]], ["passed", "failed"])
        self.assertEqual([c["sequence"] for c in spec["checks"]], [1, 2])

    def test_records_bind_capture_and_evidence_bytes(self):
        self.write([row(1)], {1: "ok\n"})
        self.run_check()
        spec = json.loads(self.out.read_text())
        self.assertEqual(spec["runs_sha256"],
                         hashlib.sha256((self.capture / "runs.jsonl").read_bytes()).hexdigest())
        artifact = spec["checks"][0]["artifacts"][0]
        evidence = self.out.parent / artifact["path"]
        self.assertEqual(artifact["sha256"], hashlib.sha256(evidence.read_bytes()).hexdigest())
        self.assertTrue(json.loads(evidence.read_text())["runs"][0]["matched"])

    def test_existing_results_sidecar_is_never_replaced(self):
        self.write([row(1)], {1: "ok\n"})
        self.out.parent.mkdir()
        sidecar = self.out.with_name("validation-results.json")
        sidecar.write_text("earlier evidence")
        with self.assertRaises(FileExistsError):
            self.run_check()
        self.assertEqual(sidecar.read_text(), "earlier evidence")
        self.assertFalse(self.out.exists())

    def test_stdout_paths_are_confined_to_the_capture(self):
        outside = self.root / "outside.txt"
        outside.write_text("ok\n")
        for path in (str(outside), "../outside.txt"):
            self.write([row(1, stdout=path)], {})
            with self.assertRaises(ValueError):
                self.run_check()
        self.assertFalse(self.out.exists())

    def test_malformed_capture_is_refused(self):
        self.write([row(1)], {1: "ok\n"})
        (self.capture / "manifest.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.run_check()
        self.write([row(1, timed_out="no")], {1: "ok\n"})
        (self.capture / "manifest.json").write_text(json.dumps(dict(
            schema="lean-profile-compare-alpha", expected_exit_code=0,
            commands={name: dict(argv=[name]) for name in ("baseline", "candidate")})))
        with self.assertRaises(ValueError):
            self.run_check()

    def test_refuses_overwrite_empty_scope_and_no_completed_runs(self):
        self.write([row(1, launch_error="missing")], {})
        with self.assertRaises(ValueError):
            self.run_check()
        self.write([row(1)], {1: "ok\n"})
        with self.assertRaises(ValueError):
            tool.check_outputs(self.capture, self.root / "expected.txt", "  ", self.out)
        self.run_check()
        with self.assertRaises(FileExistsError):
            self.run_check()

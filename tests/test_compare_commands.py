from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPARE_SCRIPT = REPOSITORY_ROOT / "scripts" / "compare_commands.py"


class CompareCommandsTests(unittest.TestCase):
    def compare_command(
        self,
        *,
        baseline: list[str],
        candidate: list[str],
        out_dir: str = "evidence",
        extra_args: list[str] | None = None,
    ) -> list[str]:
        command = [
            sys.executable,
            str(COMPARE_SCRIPT),
            "--baseline",
            json.dumps(baseline),
            "--candidate",
            json.dumps(candidate),
            "--out-dir",
            out_dir,
        ]
        if extra_args:
            command.extend(extra_args)
        return command

    def run_compare(
        self,
        cwd: Path,
        *,
        baseline: list[str],
        candidate: list[str],
        out_dir: str = "evidence",
        extra_args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if env:
            environment.update(env)
        return subprocess.run(
            self.compare_command(
                baseline=baseline,
                candidate=candidate,
                out_dir=out_dir,
                extra_args=extra_args,
            ),
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def read_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def read_jsonl(self, path: Path) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def initialize_git_repository(self, cwd: Path) -> Path:
        subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
        tracked = cwd / "tracked.txt"
        tracked.write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=cwd, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Lean Profile Tests",
                "-c",
                "user.email=tests@example.invalid",
                "commit",
                "-qm",
                "initial",
            ],
            cwd=cwd,
            check=True,
        )
        return tracked

    def write_fake_perf(
        self,
        cwd: Path,
        *,
        counter_contents: str | None = "fake counters\n",
        mutate_executable: bool = False,
    ) -> Path:
        perf = cwd / "perf"
        perf.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, subprocess, sys\n"
            f"COUNTER_CONTENTS = {counter_contents!r}\n"
            f"MUTATE_EXECUTABLE = {mutate_executable!r}\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print('perf version test-double')\n"
            "    raise SystemExit(0)\n"
            "args = sys.argv[1:]\n"
            "output = pathlib.Path(args[args.index('-o') + 1])\n"
            "if COUNTER_CONTENTS is not None:\n"
            "    output.write_text(COUNTER_CONTENTS, encoding='utf-8')\n"
            "separator = args.index('--')\n"
            "returncode = subprocess.run(args[separator + 1:]).returncode\n"
            "if MUTATE_EXECUTABLE:\n"
            "    with pathlib.Path(__file__).open('a', encoding='utf-8') as stream:\n"
            "        stream.write('# identity drift\\n')\n"
            "raise SystemExit(returncode)\n",
            encoding="utf-8",
        )
        perf.chmod(0o755)
        return perf

    def test_success_preserves_schedule_metadata_artifacts_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            artifact = cwd / "input.txt"
            artifact.write_text("representative input\n", encoding="utf-8")
            baseline = [sys.executable, "-c", "print('baseline-output')"]
            candidate = [sys.executable, "-c", "print('candidate-output')"]

            result = self.run_compare(
                cwd,
                baseline=baseline,
                candidate=candidate,
                extra_args=[
                    "--passes",
                    "2",
                    "--warmups",
                    "1",
                    "--artifact",
                    str(artifact),
                    "--metadata",
                    "build=release",
                ],
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = cwd / "evidence"
            rows = self.read_jsonl(evidence / "runs.jsonl")
            self.assertEqual(
                [(row["phase"], row["label"]) for row in rows],
                [
                    ("warmup", "baseline"),
                    ("warmup", "candidate"),
                    ("measured", "baseline"),
                    ("measured", "candidate"),
                    ("measured", "candidate"),
                    ("measured", "baseline"),
                ],
            )
            self.assertEqual([row["slot"] for row in rows], [1, 2, 1, 2, 1, 2])
            self.assertEqual([row["pass"] for row in rows], [1, 1, 1, 1, 2, 2])

            manifest = self.read_json(evidence / "manifest.json")
            self.assertEqual(manifest["metadata"], {"build": "release"})
            self.assertEqual(
                manifest["artifacts"],
                [
                    {
                        "path": str(artifact),
                        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    }
                ],
            )
            self.assertIsNone(manifest["git"])

            summary = self.read_json(evidence / "summary.json")
            self.assertEqual(summary["baseline"]["count"], 2)
            self.assertEqual(summary["candidate"]["count"], 2)
            self.assertEqual(len(summary["paired_deltas_ns"]), 2)
            self.assertIn("screening evidence", " ".join(summary["warnings"]))

            baseline_stdout = evidence / str(rows[0]["stdout"])
            candidate_stdout = evidence / str(rows[1]["stdout"])
            self.assertEqual(baseline_stdout.read_text(encoding="utf-8"), "baseline-output\n")
            self.assertEqual(candidate_stdout.read_text(encoding="utf-8"), "candidate-output\n")

    def test_command_failure_preserves_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", "pass"],
                candidate=[sys.executable, "-c", "raise SystemExit(7)"],
                extra_args=["--passes", "2", "--warmups", "0"],
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("candidate measured run failed", result.stderr)
            evidence = cwd / "evidence"
            rows = self.read_jsonl(evidence / "runs.jsonl")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["exit_code"], 7)
            self.assertTrue((evidence / "manifest.json").is_file())
            identity_check = self.read_json(evidence / "identity-check.json")
            self.assertTrue(identity_check["valid"])
            self.assertFalse((evidence / "summary.json").exists())

    def test_existing_output_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            (cwd / "evidence").mkdir()
            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", "pass"],
                candidate=[sys.executable, "-c", "pass"],
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("--out-dir already exists", result.stderr)

    def test_invalid_schedule_is_refused_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", "pass"],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=["--passes", "3"],
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("positive even number", result.stderr)
            self.assertFalse((cwd / "evidence").exists())

    @unittest.skipUnless(os.name == "posix", "executable permission is POSIX-specific")
    def test_non_executable_command_is_refused_during_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            command = cwd / "not-executable"
            command.write_text("not executable\n", encoding="utf-8")
            command.chmod(0o644)

            result = self.run_compare(
                cwd,
                baseline=[str(command)],
                candidate=[sys.executable, "-c", "pass"],
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("executable is not executable", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((cwd / "evidence").exists())

    @unittest.skipUnless(os.name == "posix", "invalid shebang behavior is POSIX-specific")
    def test_launch_error_preserves_structured_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            command = cwd / "invalid-interpreter"
            command.write_text("#!/definitely/missing/interpreter\n", encoding="utf-8")
            command.chmod(0o755)

            result = self.run_compare(
                cwd,
                baseline=[str(command)],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=["--passes", "2", "--warmups", "0"],
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("baseline measured run failed", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            evidence = cwd / "evidence"
            rows = self.read_jsonl(evidence / "runs.jsonl")
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["timed_out"])
            self.assertIsNone(rows[0]["exit_code"])
            self.assertIn("FileNotFoundError", rows[0]["launch_error"])
            run_stderr = evidence / str(rows[0]["stderr"])
            self.assertIn("FileNotFoundError", run_stderr.read_text(encoding="utf-8"))
            identity_check = self.read_json(evidence / "identity-check.json")
            self.assertTrue(identity_check["valid"])

    def test_duplicate_metadata_keys_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", "pass"],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=[
                    "--metadata",
                    "build=release",
                    "--metadata",
                    "build=debug",
                ],
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("duplicate metadata key: 'build'", result.stderr)
            self.assertFalse((cwd / "evidence").exists())

    def test_identical_commands_produce_a_control_run_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            command = [sys.executable, "-c", "pass"]
            result = self.run_compare(
                cwd,
                baseline=command,
                candidate=command,
                extra_args=["--passes", "2", "--warmups", "0"],
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = self.read_json(cwd / "evidence" / "summary.json")
            self.assertIn(
                "Baseline and candidate argv are identical; interpret this as a noise-control run.",
                summary["warnings"],
            )
            self.assertIn("Baseline and candidate argv are identical", result.stderr)

    def test_expected_nonzero_exit_code_can_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            command = [sys.executable, "-c", "raise SystemExit(7)"]
            result = self.run_compare(
                cwd,
                baseline=command,
                candidate=command,
                extra_args=[
                    "--passes",
                    "2",
                    "--warmups",
                    "0",
                    "--expected-exit-code",
                    "7",
                ],
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = self.read_jsonl(cwd / "evidence" / "runs.jsonl")
            self.assertEqual([row["exit_code"] for row in rows], [7, 7, 7, 7])

    @unittest.skipUnless(os.name == "posix", "fake perf executable uses a POSIX shebang")
    def test_perf_wrapper_preserves_one_counter_file_per_measured_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            perf = self.write_fake_perf(cwd)

            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", "pass"],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=[
                    "--passes",
                    "2",
                    "--warmups",
                    "0",
                    "--perf-events",
                    "cycles:u,instructions:u",
                ],
                env={"PATH": f"{cwd}{os.pathsep}{os.environ.get('PATH', '')}"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = cwd / "evidence"
            manifest = self.read_json(evidence / "manifest.json")
            self.assertEqual(manifest["perf"]["version"], "perf version test-double")
            self.assertEqual(
                manifest["perf"]["executable_sha256"],
                hashlib.sha256(perf.read_bytes()).hexdigest(),
            )
            rows = self.read_jsonl(evidence / "runs.jsonl")
            counter_paths = [evidence / str(row["perf_stat"]) for row in rows]
            self.assertEqual(len(counter_paths), 4)
            self.assertTrue(all(path.read_text() == "fake counters\n" for path in counter_paths))
            self.assertEqual(
                [row["perf_stat_sha256"] for row in rows],
                [hashlib.sha256(path.read_bytes()).hexdigest() for path in counter_paths],
            )
            self.assertTrue(all(row["evidence_error"] is None for row in rows))

    @unittest.skipUnless(os.name == "posix", "fake perf executable uses a POSIX shebang")
    def test_missing_or_empty_perf_counter_fails_with_structured_evidence(self) -> None:
        for expected_error, counter_contents in (("missing", None), ("empty", "")):
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory() as temporary:
                    cwd = Path(temporary)
                    self.write_fake_perf(cwd, counter_contents=counter_contents)

                    result = self.run_compare(
                        cwd,
                        baseline=[sys.executable, "-c", "pass"],
                        candidate=[sys.executable, "-c", "pass"],
                        extra_args=[
                            "--passes",
                            "2",
                            "--warmups",
                            "0",
                            "--perf-events",
                            "cycles:u",
                        ],
                        env={
                            "PATH": f"{cwd}{os.pathsep}{os.environ.get('PATH', '')}"
                        },
                    )

                    self.assertEqual(result.returncode, 1)
                    self.assertNotIn("Traceback", result.stderr)
                    evidence = cwd / "evidence"
                    rows = self.read_jsonl(evidence / "runs.jsonl")
                    self.assertEqual(len(rows), 1)
                    self.assertIn(expected_error, rows[0]["evidence_error"])
                    self.assertIsNone(rows[0]["perf_stat_sha256"])
                    self.assertTrue(
                        self.read_json(evidence / "identity-check.json")["valid"]
                    )

    @unittest.skipUnless(os.name == "posix", "fake perf executable uses a POSIX shebang")
    def test_perf_executable_drift_invalidates_a_completed_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            self.write_fake_perf(cwd, mutate_executable=True)

            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", "pass"],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=[
                    "--passes",
                    "2",
                    "--warmups",
                    "0",
                    "--perf-events",
                    "cycles:u",
                ],
                env={"PATH": f"{cwd}{os.pathsep}{os.environ.get('PATH', '')}"},
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("identity drift detected", result.stderr)
            evidence = cwd / "evidence"
            identity_check = self.read_json(evidence / "identity-check.json")
            self.assertFalse(identity_check["valid"])
            self.assertEqual(
                [change["subject"] for change in identity_check["changes"]],
                ["tool:perf"],
            )
            self.assertFalse(self.read_json(evidence / "summary.json")["identity_check"]["valid"])

    @unittest.skipUnless(os.name == "posix", "SIGINT handling is POSIX-specific")
    def test_interrupt_preserves_run_and_identity_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            started = cwd / "started"
            baseline = [
                sys.executable,
                "-c",
                (
                    "import pathlib,time;"
                    f"pathlib.Path({str(started)!r}).write_text('started');"
                    "time.sleep(5)"
                ),
            ]
            process = subprocess.Popen(
                self.compare_command(
                    baseline=baseline,
                    candidate=[sys.executable, "-c", "pass"],
                    extra_args=["--passes", "2", "--warmups", "0"],
                ),
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 3
                while (
                    not started.exists()
                    and process.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                self.assertTrue(started.exists(), "comparison did not start its first command")
                process.send_signal(signal.SIGINT)
                _stdout, stderr = process.communicate(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

            self.assertEqual(process.returncode, 130, stderr)
            self.assertNotIn("Traceback", stderr)
            evidence = cwd / "evidence"
            rows = self.read_jsonl(evidence / "runs.jsonl")
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["interrupted"])
            self.assertIsNone(rows[0]["exit_code"])
            self.assertFalse(rows[0]["timed_out"])
            self.assertTrue(self.read_json(evidence / "identity-check.json")["valid"])
            self.assertFalse((evidence / "summary.json").exists())

    def test_artifact_drift_invalidates_a_completed_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            artifact = cwd / "input.txt"
            artifact.write_text("before\n", encoding="utf-8")
            mutate_artifact = (
                "import pathlib;"
                f"pathlib.Path({str(artifact)!r}).write_text('after\\n')"
            )
            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", mutate_artifact],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=[
                    "--passes",
                    "2",
                    "--warmups",
                    "0",
                    "--artifact",
                    str(artifact),
                ],
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("identity drift detected", result.stderr)
            evidence = cwd / "evidence"
            identity_check = self.read_json(evidence / "identity-check.json")
            self.assertFalse(identity_check["valid"])
            self.assertEqual(
                [change["subject"] for change in identity_check["changes"]],
                [f"artifact:{artifact}"],
            )
            summary = self.read_json(evidence / "summary.json")
            self.assertFalse(summary["identity_check"]["valid"])

    def test_tracked_git_drift_invalidates_a_completed_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            tracked = self.initialize_git_repository(cwd)
            mutate_tracked = (
                "import pathlib;"
                f"pathlib.Path({str(tracked)!r}).write_text('changed\\n')"
            )

            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", mutate_tracked],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=["--passes", "2", "--warmups", "0"],
            )

            self.assertEqual(result.returncode, 1)
            identity_check = self.read_json(cwd / "evidence" / "identity-check.json")
            self.assertFalse(identity_check["valid"])
            self.assertEqual(
                [change["subject"] for change in identity_check["changes"]],
                ["git"],
            )

    def test_dirty_git_patch_is_preserved_without_output_false_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            tracked = self.initialize_git_repository(cwd)
            tracked.write_text("dirty before comparison\n", encoding="utf-8")

            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", "pass"],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=["--passes", "2", "--warmups", "0"],
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = cwd / "evidence"
            manifest = self.read_json(evidence / "manifest.json")
            git_identity = manifest["git"]
            self.assertIsInstance(git_identity, dict)
            self.assertEqual(git_identity["status_porcelain"], [" M tracked.txt"])
            patch = evidence / "git-tracked.patch"
            self.assertTrue(patch.is_file())
            self.assertIn(b"dirty before comparison", patch.read_bytes())
            identity_check = self.read_json(evidence / "identity-check.json")
            self.assertTrue(identity_check["valid"])

    @unittest.skipUnless(os.name == "posix", "process-group cleanup is POSIX-specific")
    def test_timeout_kills_descendant_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            leaked_marker = cwd / "descendant-survived"
            descendant = (
                "import pathlib,signal,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                "time.sleep(0.4);"
                f"pathlib.Path({str(leaked_marker)!r}).write_text('leaked')"
            )
            parent = (
                "import subprocess,sys,time;"
                f"subprocess.Popen([sys.executable,'-c',{descendant!r}]);"
                "time.sleep(5)"
            )

            result = self.run_compare(
                cwd,
                baseline=[sys.executable, "-c", parent],
                candidate=[sys.executable, "-c", "pass"],
                extra_args=[
                    "--passes",
                    "2",
                    "--warmups",
                    "0",
                    "--timeout-seconds",
                    "0.1",
                ],
            )

            self.assertEqual(result.returncode, 1)
            rows = self.read_jsonl(cwd / "evidence" / "runs.jsonl")
            self.assertTrue(rows[0]["timed_out"])
            identity_check = self.read_json(cwd / "evidence" / "identity-check.json")
            self.assertTrue(identity_check["valid"])
            time.sleep(0.6)
            self.assertFalse(leaked_marker.exists())


if __name__ == "__main__":
    unittest.main()

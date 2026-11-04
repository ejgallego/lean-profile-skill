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
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPARE_SCRIPT = REPOSITORY_ROOT / "scripts" / "compare_commands.py"
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
import compare_commands
from compare_commands import summarize_comparison, wait_for_exit, write_json


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class WaitForExitTests(unittest.TestCase):
    def spawn(self, *argv: str) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(list(argv), start_new_session=True)
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def without_pidfd(self) -> mock._patch:
        return mock.patch.object(
            compare_commands.os, "pidfd_open", side_effect=OSError("unavailable"), create=True
        )

    def test_completed_child_reports_its_code_without_any_signal(self) -> None:
        process = self.spawn("sh", "-c", "exit 3")
        with mock.patch.object(compare_commands, "terminate_process_group") as terminate:
            self.assertEqual(wait_for_exit(process, 30)[:3], (3, False, False))
        terminate.assert_not_called()

    def test_deadline_terminates_without_reporting_an_exit_code(self) -> None:
        process = self.spawn("sleep", "30")
        self.assertEqual(wait_for_exit(process, 0.05)[:3], (None, True, False))
        self.assertIsNotNone(process.poll())

    def test_exit_after_the_deadline_check_counts_as_completion(self) -> None:
        process = self.spawn("true")
        if compare_commands.await_exit_unreaped(process, 5) is None:
            process.wait()
        with mock.patch.object(compare_commands, "observe_exit", return_value=(False, "pidfd")), \
                mock.patch.object(compare_commands, "terminate_process_group") as terminate:
            self.assertEqual(wait_for_exit(process, 30)[:3], (0, False, False))
        terminate.assert_not_called()

    def test_interrupt_terminates_the_child(self) -> None:
        process = self.spawn("sleep", "30")
        with mock.patch.object(compare_commands, "observe_exit", side_effect=KeyboardInterrupt):
            self.assertEqual(wait_for_exit(process, 30)[:3], (None, False, True))
        self.assertIsNotNone(process.poll())

    def test_failed_observer_keeps_the_deadline_and_reports_the_method(self) -> None:
        for failure in (self.without_pidfd(), mock.patch.object(
                compare_commands.select, "select", side_effect=OSError("boom"))):
            process = self.spawn("sleep", "30")
            started = time.monotonic()
            with failure:
                result = wait_for_exit(process, 0.05)
            self.assertEqual(result[:3], (None, True, False))
            self.assertEqual(result.exit_observation, "timed-polling")
            self.assertLess(time.monotonic() - started, 5)
            self.assertIsNotNone(process.poll())

    def test_fallback_reports_a_normal_exit(self) -> None:
        process = self.spawn("sh", "-c", "exit 4")
        with self.without_pidfd():
            result = wait_for_exit(process, 30)
        self.assertEqual(result[:3], (4, False, False))
        self.assertEqual(compare_commands.fallback_observation(None), "blocking-wait")

    @unittest.skipUnless(hasattr(os, "pidfd_open"), "needs pidfd_open")
    def test_exit_is_observed_without_reaping_the_process_group(self) -> None:
        process = self.spawn("true")
        self.assertTrue(compare_commands.await_exit_unreaped(process, 5))
        self.assertIsNone(process.returncode)
        os.killpg(process.pid, 0)  # Still reserved, so signaling it cannot hit a stranger.

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_root_stays_unreaped_through_the_final_group_signal(self) -> None:
        process = self.spawn("sleep", "30")
        seen: list[tuple[int, int | None]] = []
        real_killpg = os.killpg

        def record(group: int, number: int) -> None:
            seen.append((number, process.returncode))
            real_killpg(group, number)

        with mock.patch.object(compare_commands.os, "killpg", side_effect=record):
            self.assertIsNone(compare_commands.terminate_process_group(process))
        self.assertEqual(seen, [(signal.SIGTERM, None), (signal.SIGKILL, None)])
        self.assertIsNotNone(process.returncode)

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_denied_group_signal_on_a_live_child_is_bounded_and_reported(self) -> None:
        process = self.spawn("sleep", "30")
        started = time.monotonic()
        with mock.patch.object(compare_commands.os, "killpg", side_effect=PermissionError), \
                mock.patch.object(compare_commands, "CLEANUP_SECONDS", 0.05):
            result = wait_for_exit(process, 0.05)
        self.assertEqual(result[:3], (None, True, False))
        self.assertIn("killed the root process only", result.cleanup_error)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIsNotNone(process.poll())

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_denied_signal_to_an_exited_root_is_not_an_error(self) -> None:
        process = self.spawn("true")
        if compare_commands.await_exit_unreaped(process, 5) is None:
            process.wait()
        with mock.patch.object(compare_commands.os, "killpg", side_effect=PermissionError):
            self.assertIsNone(compare_commands.terminate_process_group(process))

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_denied_group_and_direct_signals_are_bounded_and_reported(self) -> None:
        process = self.spawn("sleep", "30")
        started = time.monotonic()
        with mock.patch.object(compare_commands.os, "killpg", side_effect=PermissionError), \
                mock.patch.object(process, "kill", side_effect=PermissionError("direct denied")), \
                mock.patch.object(compare_commands, "CLEANUP_SECONDS", 0.02):
            error = compare_commands.terminate_process_group(process)
        self.assertIn("process may still be running", error)
        self.assertIn("direct denied", error)
        self.assertLess(time.monotonic() - started, 5)

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_capture_preserves_a_cleanup_failure_as_a_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(compare_commands.os, "killpg", side_effect=PermissionError), \
                    mock.patch.object(subprocess.Popen, "kill", side_effect=PermissionError("denied")):
                status, evidence = self.capture(Path(temp_dir), command='["sleep", "1"]', deadline="0.05",
                                                CLEANUP_SECONDS=0.02)
            self.assertNotEqual(status, 0)
            row = json.loads((evidence / "runs.jsonl").read_text().splitlines()[0])
            self.assertTrue(row["timed_out"])
            self.assertIsNone(row["exit_code"])
            self.assertIn("process may still be running", row["evidence_error"])
            self.assertTrue((evidence / "identity-check.json").is_file())

    def capture(self, cwd: Path, *, command: str = '["true"]', deadline: str = "30",
                **patches: object) -> tuple[int, Path]:
        """Run the real entry point in-process so a fault can be injected."""
        argv = ["compare_commands.py", "--baseline", command, "--candidate", '["sh", "-c", "true"]',
                "--out-dir", str(cwd / "evidence"), "--timeout-seconds", deadline]
        with mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout"), mock.patch("sys.stderr"), \
                mock.patch.multiple(compare_commands, **patches):
            return compare_commands.main(), cwd / "evidence"

    def test_capture_records_the_method_each_run_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            status, evidence = self.capture(
                Path(temp_dir), planned_exit_observation=lambda _: "pidfd",
                await_exit_unreaped=mock.Mock(side_effect=lambda process, _: process.wait() is not None))
            self.assertEqual(status, 0)
            rows = [json.loads(line) for line in (evidence / "runs.jsonl").read_text().splitlines()]
            self.assertEqual({row["exit_observation"] for row in rows}, {"pidfd"})
            manifest = json.loads((evidence / "manifest.json").read_text())
            self.assertEqual(manifest["elapsed_measurement"]["planned_exit_observation"], "pidfd")

    def test_capture_rejects_a_run_whose_exit_method_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            status, evidence = self.capture(
                Path(temp_dir), planned_exit_observation=lambda _: "pidfd",
                await_exit_unreaped=mock.Mock(return_value=None))
            self.assertNotEqual(status, 0)
            row = json.loads((evidence / "runs.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["exit_observation"], "timed-polling")
            self.assertIn("planned pidfd", row["evidence_error"])

    def test_host_that_must_poll_warns_in_the_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, evidence = self.capture(
                Path(temp_dir), planned_exit_observation=lambda _: "timed-polling",
                await_exit_unreaped=mock.Mock(return_value=None))
            manifest = json.loads((evidence / "manifest.json").read_text())
            self.assertIn("cannot observe exit without polling", " ".join(manifest["warnings"]))


class OutputWarningTests(unittest.TestCase):
    def rows(self, baseline: list[str], candidate: list[str]) -> list[dict[str, str]]:
        return [dict(phase="measured", label=label, stdout_sha256=digest)
                for label, digests in (("baseline", baseline), ("candidate", candidate))
                for digest in digests]

    def test_matching_outputs_stay_quiet(self) -> None:
        self.assertEqual(compare_commands.output_warnings(self.rows(["a", "a"], ["a", "a"])), [])

    def test_arm_difference_is_reported(self) -> None:
        warnings = compare_commands.output_warnings(self.rows(["a"], ["b"]))
        self.assertIn("stdout differ", " ".join(warnings))

    def test_varying_output_says_bytes_cannot_compare(self) -> None:
        warnings = compare_commands.output_warnings(self.rows(["a", "b"], ["a"]))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Baseline stdout varies", warnings[0])

    def test_both_sides_varying_over_the_same_hashes_are_both_reported(self) -> None:
        warnings = compare_commands.output_warnings(self.rows(["a", "b"], ["b", "a"]))
        self.assertEqual(len(warnings), 2)

    def test_missing_hashes_or_side_report_nothing(self) -> None:
        self.assertEqual(compare_commands.output_warnings(self.rows([], ["a"])), [])
        rows = [dict(phase="measured", label="baseline")] + self.rows([], ["a"])
        self.assertEqual(compare_commands.output_warnings(rows), [])

    def test_warmups_do_not_count(self) -> None:
        rows = self.rows(["a"], ["a"]) + [dict(phase="warmup", label="candidate", stdout_sha256="b")]
        self.assertEqual(compare_commands.output_warnings(rows), [])


class ShortRunWarningTests(unittest.TestCase):
    def test_long_arms_stay_quiet(self) -> None:
        self.assertEqual(compare_commands.short_run_warnings({"baseline": 8e9, "candidate": 1e8}), [])

    def test_only_the_short_arm_is_named(self) -> None:
        warnings = compare_commands.short_run_warnings({"baseline": 8.3e9, "candidate": 38.6e6})
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("Candidate median is 38.6 ms"))
        self.assertIn("zero-work run", warnings[0])

    def test_each_short_arm_is_named(self) -> None:
        warnings = compare_commands.short_run_warnings({"baseline": 5e6, "candidate": 4e6})
        self.assertEqual([w.split()[0] for w in warnings], ["Baseline", "Candidate"])

    def test_missing_median_is_skipped(self) -> None:
        self.assertEqual(compare_commands.short_run_warnings({"baseline": None, "candidate": 2e8}), [])


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
            timeout=30,
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
                "commit.gpgsign=false",
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
                manifest["elapsed_measurement"]["scope"],
                "child-process wall time including process startup",
            )
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
            measured = {(r["pass"], r["label"]): r["elapsed_ns"]
                        for r in rows if r["phase"] == "measured"}
            self.assertEqual(summary["paired_savings_ns"],
                             [measured[p, "baseline"] - measured[p, "candidate"]
                              for p in (1, 2)])
            self.assertIn("screening evidence", " ".join(summary["warnings"]))
            self.assertIn("Baseline and candidate stdout differ", " ".join(summary["warnings"]))
            self.assertEqual(rows[0]["stdout_sha256"], sha256_text("baseline-output\n"))

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

    def test_identical_launchers_warn_without_claiming_an_a_a_control(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            baseline = cwd / "baseline"
            baseline.write_text("#!/bin/sh\necho same\n", encoding="utf-8")
            baseline.chmod(0o755)
            candidate = cwd / "candidate"
            candidate.write_bytes(baseline.read_bytes())
            candidate.chmod(0o755)
            result = subprocess.run(
                self.compare_command(baseline=[str(baseline)], candidate=[str(candidate)]),
                cwd=cwd, capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = self.read_json(cwd / "evidence" / "manifest.json")
            warnings = " ".join(manifest["warnings"])
            self.assertIn("byte-identical executables", warnings)
            self.assertIn("A/A control only if loaded libraries", warnings)

    def test_invalid_timeout_is_refused_before_launch_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            command = [sys.executable, "-c", "from pathlib import Path; Path('launched').touch()"]
            for value in ("0", "-1", "nan", "NaN", "inf", "-inf", "1e309"):
                with self.subTest(value=value):
                    result = self.run_compare(
                        cwd, baseline=command, candidate=command,
                        extra_args=[f"--timeout-seconds={value}"],
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("finite and positive", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertFalse((cwd / "evidence").exists())
                    self.assertFalse((cwd / "launched").exists())

    def test_summary_uses_matched_savings_not_difference_of_medians(self) -> None:
        # Asymmetric samples distinguish group medians from paired differences.
        rows = []
        for p, (a, b) in enumerate(zip((10, 100, 20, 30), (9, 90, 25, 29)), 1):
            for name, value in (("candidate", b), ("baseline", a)):
                rows.append(dict(phase="measured", label=name, elapsed_ns=value, **{"pass": p}))
        rows.append(dict(phase="warmup", label="baseline", elapsed_ns=1_000_000, **{"pass": 1}))
        result = summarize_comparison(rows)
        self.assertEqual(result["baseline"]["count"], 4)
        self.assertEqual(result["paired_savings_ns"], [1, 10, -5, 1])
        self.assertEqual(result["paired_saving_median_ns"], 1)
        self.assertEqual(result["baseline_minus_candidate_median_ns"], -2)
        self.assertAlmostEqual(result["median_reduction_pct"], -8)
        self.assertNotIn("paired_deltas_ns", result)
        self.assertNotIn("candidate_minus_baseline_median_percent", result)

    def test_json_writer_rejects_nonfinite_values_before_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        write_json(path, {"nested": [value]})
                    self.assertFalse(path.exists())

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
            self.assertEqual(len(manifest["load_average"]), 3)
            self.assertIn(manifest["elapsed_measurement"]["planned_exit_observation"],
                          ("pidfd", "timed-polling", "blocking-wait"))
            self.assertIsNone(manifest["git"])
            self.assertIn("no commit is recorded", " ".join(manifest["warnings"]))
            self.assertIn("perf stat wrapper", manifest["elapsed_measurement"]["scope"])
            self.assertIn(
                "separate comparison without --perf-events",
                " ".join(manifest["warnings"]),
            )
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
            summary = self.read_json(evidence / "summary.json")
            self.assertIn(
                "separate comparison without --perf-events",
                " ".join(summary["warnings"]),
            )

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

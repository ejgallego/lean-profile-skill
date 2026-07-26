#!/usr/bin/env python3
"""Run two commands in an order-balanced schedule and preserve raw evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def parse_command(value: str, option: str) -> list[str]:
    try:
        command = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(f"{option} must be a JSON array: {error}") from error
    if not isinstance(command, list) or not command or not all(
        isinstance(arg, str) for arg in command
    ):
        raise argparse.ArgumentTypeError(f"{option} must be a nonempty JSON array of strings")
    return command


def parse_metadata(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key:
            raise ValueError(f"metadata must have KEY=VALUE form: {value!r}")
        result[key] = item
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_executable(command: list[str], cwd: Path) -> Path:
    executable = command[0]
    has_directory = any(
        separator is not None and separator in executable
        for separator in (os.sep, os.altsep)
    )
    if has_directory:
        path = Path(executable)
        if not path.is_absolute():
            path = cwd / path
        resolved = path.resolve()
    else:
        found = shutil.which(executable)
        if found is None:
            raise FileNotFoundError(f"executable not found: {executable}")
        resolved = Path(found).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"executable is not a file: {resolved}")
    return resolved


def git_output(cwd: Path, *args: str, binary: bool = False) -> str | bytes | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=not binary,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def git_identity(cwd: Path) -> tuple[dict[str, Any] | None, bytes | None]:
    root_text = git_output(cwd, "rev-parse", "--show-toplevel")
    if not isinstance(root_text, str):
        return None, None
    root = Path(root_text.strip())
    head_text = git_output(cwd, "rev-parse", "HEAD")
    status_text = git_output(cwd, "status", "--porcelain=v1", "--untracked-files=all")
    diff = git_output(cwd, "diff", "--binary", "--full-index", "HEAD", binary=True)
    identity = {
        "root": str(root),
        "head": head_text.strip() if isinstance(head_text, str) else None,
        "status_porcelain": status_text.splitlines() if isinstance(status_text, str) else None,
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest()
        if isinstance(diff, bytes)
        else None,
        "tracked_diff_path": "git-tracked.patch" if diff else None,
    }
    return identity, diff if diff else None


def command_identity(command: list[str], cwd: Path) -> dict[str, Any]:
    executable = resolve_executable(command, cwd)
    return {
        "argv": command,
        "executable": str(executable),
        "executable_sha256": sha256_file(executable),
    }


def summarize(values: list[int]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "min_ns": min(values),
        "median_ns": statistics.median(values),
        "mean_ns": statistics.fmean(values),
        "max_ns": max(values),
        "stdev_ns": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two commands with alternating AB/BA passes and raw JSONL output."
    )
    parser.add_argument("--baseline", required=True, help="baseline argv as a JSON array")
    parser.add_argument("--candidate", required=True, help="candidate argv as a JSON array")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--passes", type=int, default=2, help="positive even pass count")
    parser.add_argument("--warmups", type=int, default=1, help="warmups per command")
    parser.add_argument("--expected-exit-code", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--artifact", action="append", default=[], type=Path)
    parser.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument(
        "--perf-events",
        help="comma-separated perf stat events; produces one counter file per measured run",
    )
    args = parser.parse_args()

    if args.passes <= 0 or args.passes % 2 != 0:
        parser.error("--passes must be a positive even number")
    if args.warmups < 0:
        parser.error("--warmups must be nonnegative")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    try:
        baseline = parse_command(args.baseline, "--baseline")
        candidate = parse_command(args.candidate, "--candidate")
        metadata = parse_metadata(args.metadata)
    except (argparse.ArgumentTypeError, ValueError) as error:
        parser.error(str(error))

    cwd = Path.cwd().resolve()
    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = cwd / out_dir
    out_dir = out_dir.resolve()
    if out_dir.exists():
        parser.error(f"--out-dir already exists: {out_dir}")

    try:
        commands = {
            "baseline": command_identity(baseline, cwd),
            "candidate": command_identity(candidate, cwd),
        }
        artifacts = []
        for artifact_arg in args.artifact:
            artifact = artifact_arg if artifact_arg.is_absolute() else cwd / artifact_arg
            artifact = artifact.resolve()
            if not artifact.is_file():
                raise FileNotFoundError(f"artifact is not a file: {artifact}")
            artifacts.append({"path": str(artifact), "sha256": sha256_file(artifact)})
    except (FileNotFoundError, OSError) as error:
        parser.error(str(error))

    perf = None
    perf_version = None
    if args.perf_events:
        perf = shutil.which("perf")
        if perf is None:
            parser.error("--perf-events requires perf on PATH")
        perf_version = subprocess.run(
            [perf, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        ).stdout.strip()

    git, tracked_diff = git_identity(cwd)
    manifest = {
        "schema": "lean-profile-compare-alpha",
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cwd": str(cwd),
        "platform": platform.uname()._asdict(),
        "python": sys.version,
        "commands": commands,
        "artifacts": artifacts,
        "git": git,
        "schedule": {"passes": args.passes, "warmups_per_command": args.warmups},
        "elapsed_measurement": {
            "clock": "time.perf_counter_ns",
            "scope": "child-process wall time including process startup",
        },
        "expected_exit_code": args.expected_exit_code,
        "timeout_seconds": args.timeout_seconds,
        "perf": {
            "path": perf,
            "version": perf_version,
            "events": args.perf_events,
            "inherit": True,
        }
        if perf
        else None,
        "metadata": metadata,
    }

    out_dir.mkdir(parents=True)
    (out_dir / "stdout").mkdir()
    (out_dir / "stderr").mkdir()
    if perf:
        (out_dir / "perf-stat").mkdir()
    if tracked_diff is not None:
        (out_dir / "git-tracked.patch").write_bytes(tracked_diff)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    rows: list[dict[str, Any]] = []
    sequence = 0

    def run_one(label: str, phase: str, pass_number: int | None, slot: int) -> bool:
        nonlocal sequence
        sequence += 1
        command = baseline if label == "baseline" else candidate
        stem = f"{sequence:03d}-{phase}-{label}"
        stdout_path = out_dir / "stdout" / f"{stem}.txt"
        stderr_path = out_dir / "stderr" / f"{stem}.txt"
        counter_path = (
            out_dir / "perf-stat" / f"{stem}.txt"
            if perf and phase == "measured"
            else None
        )
        invoked = command
        if counter_path is not None:
            invoked = [
                perf,
                "stat",
                "-e",
                args.perf_events,
                "-o",
                str(counter_path),
                "--",
                *command,
            ]

        started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        started_ns = time.perf_counter_ns()
        timed_out = False
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                result = subprocess.run(
                    invoked,
                    cwd=cwd,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=args.timeout_seconds,
                    check=False,
                )
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = None
        elapsed_ns = time.perf_counter_ns() - started_ns
        row = {
            "sequence": sequence,
            "phase": phase,
            "pass": pass_number,
            "slot": slot,
            "label": label,
            "argv": command,
            "started_at_utc": started_at,
            "elapsed_ns": elapsed_ns,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": str(stdout_path.relative_to(out_dir)),
            "stderr": str(stderr_path.relative_to(out_dir)),
            "perf_stat": str(counter_path.relative_to(out_dir)) if counter_path else None,
        }
        rows.append(row)
        with (out_dir / "runs.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        return not timed_out and exit_code == args.expected_exit_code

    for warmup in range(1, args.warmups + 1):
        for slot, label in enumerate(("baseline", "candidate"), start=1):
            if not run_one(label, "warmup", warmup, slot):
                print(f"{label} warmup failed; evidence preserved in {out_dir}", file=sys.stderr)
                return 1

    for pass_number in range(1, args.passes + 1):
        order = ("baseline", "candidate") if pass_number % 2 else ("candidate", "baseline")
        for slot, label in enumerate(order, start=1):
            if not run_one(label, "measured", pass_number, slot):
                print(
                    f"{label} measured run failed; evidence preserved in {out_dir}",
                    file=sys.stderr,
                )
                return 1

    measured = [row for row in rows if row["phase"] == "measured"]
    baseline_ns = [row["elapsed_ns"] for row in measured if row["label"] == "baseline"]
    candidate_ns = [row["elapsed_ns"] for row in measured if row["label"] == "candidate"]
    paired_deltas = []
    for pass_number in range(1, args.passes + 1):
        pair = {row["label"]: row["elapsed_ns"] for row in measured if row["pass"] == pass_number}
        paired_deltas.append(pair["candidate"] - pair["baseline"])

    baseline_summary = summarize(baseline_ns)
    candidate_summary = summarize(candidate_ns)
    baseline_median = float(baseline_summary["median_ns"])
    candidate_median = float(candidate_summary["median_ns"])
    warnings = []
    if min(baseline_median, candidate_median) < 100_000_000:
        warnings.append(
            "Median runtime is under 100 ms; process startup and timer noise may dominate."
        )
    if args.passes == 2:
        warnings.append(
            "Two passes are one AB/BA cycle and should be treated as screening evidence."
        )
    summary = {
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "candidate_minus_baseline_median_ns": candidate_median - baseline_median,
        "candidate_minus_baseline_median_percent": (
            (candidate_median - baseline_median) / baseline_median * 100
            if baseline_median
            else None
        ),
        "paired_delta_median_ns": statistics.median(paired_deltas),
        "paired_deltas_ns": paired_deltas,
        "warnings": warnings,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Raw evidence: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

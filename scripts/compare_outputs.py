#!/usr/bin/env python3
"""Run baseline and candidate over several argument sets and compare their output bytes.

Nothing is timed. Each case appends its arguments to both commands, runs them
sequentially, and retains stdout, stderr, exit status and hashes. A case
matches when both sides exit with the expected status and their stdout bytes
agree, and stderr too with `--compare-stderr`. With `--repeat`, a side whose
output varies between runs is reported as unstable rather than compared.
Executables and the Git state are rechecked afterwards. Exit 0 means every
case matched and nothing drifted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from compare_commands import (check_identity, command_identity, git_identity, parse_command,
                              sha256_file, wait_for_exit, write_json)

SCHEMA = "lean-profile-output-comparison-alpha"
LABELS = ("baseline", "candidate")


def parse_case(value: str) -> list[str]:
    try:
        case = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError(f"--case must be a JSON array: {error}") from error
    if not isinstance(case, list) or not all(isinstance(arg, str) for arg in case):
        raise argparse.ArgumentTypeError("--case must be a JSON array of strings, possibly empty")
    return case


def run_once(argv: list[str], timeout: float | None, out_dir: Path, stem: str) -> dict[str, Any]:
    """Run to completion with the harness's bounded wait and cleanup; output goes to files."""
    paths = {stream: out_dir / f"{stem}.{stream}" for stream in ("stdout", "stderr")}
    with paths["stdout"].open("wb") as stdout, paths["stderr"].open("wb") as stderr:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       start_new_session=os.name == "posix")
        except OSError as error:
            result = dict(exit_code=None, timed_out=False, interrupted=False,
                          launch_error=str(error), cleanup_error=None)
        else:
            ended = wait_for_exit(process, timeout)
            result = dict(exit_code=ended.exit_code, timed_out=ended.timed_out,
                          interrupted=ended.interrupted, launch_error=None,
                          cleanup_error=ended.cleanup_error)
    for stream, path in paths.items():
        result[stream] = path.name
        result[f"{stream}_sha256"] = sha256_file(path)
    return result


def side_outcome(runs: list[dict[str, Any]], expected_exit_code: int,
                 compare_stderr: bool) -> tuple[str, tuple | None]:
    """Collapse one side's repeats into a fingerprint, or say why it has none."""
    if any(run["launch_error"] for run in runs):
        return "failed to launch", None
    if any(run["timed_out"] for run in runs):
        return "timed out", None
    unexpected = sorted({run["exit_code"] for run in runs if run["exit_code"] != expected_exit_code},
                        key=str)
    if unexpected:
        # A shared crash or rejected input says nothing about preserved results.
        return f"exited {', '.join(map(str, unexpected))}, expected {expected_exit_code}", None
    prints = {(run["stdout_sha256"], run["stderr_sha256"] if compare_stderr else None) for run in runs}
    if len(prints) > 1:
        return "unstable", None
    return "stable", prints.pop()


def verdict(sides: dict[str, tuple[str, tuple | None]]) -> str:
    states = {state for state, _ in sides.values()}
    if states - {"stable", "unstable"}:
        return "error"
    if "unstable" in states:
        return "unstable"
    return "match" if sides["baseline"][1] == sides["candidate"][1] else "differ"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", required=True, help="baseline argv as a JSON array")
    parser.add_argument("--candidate", required=True, help="candidate argv as a JSON array")
    parser.add_argument("--case", dest="cases", action="append", type=parse_case, required=True,
                        help="extra arguments for one case as a JSON array; repeat per case, "
                             "and use [] for the commands alone")
    parser.add_argument("--expected-exit-code", type=int, default=0,
                        help="status both sides must exit with for a case to match")
    parser.add_argument("--repeat", type=int, default=1, help="runs per side per case")
    parser.add_argument("--compare-stderr", action="store_true",
                        help="also require identical stderr bytes")
    parser.add_argument("--timeout-seconds", type=float, help="limit for each run")
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    commands = {label: parse_command(getattr(args, label), f"--{label}") for label in LABELS}
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    if args.timeout_seconds is not None and not (
        math.isfinite(args.timeout_seconds) and args.timeout_seconds > 0
    ):
        parser.error("--timeout-seconds must be finite and positive")
    out_dir = args.out_dir
    if out_dir.exists():
        parser.error(f"refusing to overwrite {out_dir}")
    cwd = Path.cwd()
    identities = {label: command_identity(command, cwd) for label, command in commands.items()}
    git, _ = git_identity(cwd)
    out_dir.mkdir(parents=True)
    write_json(out_dir / "manifest.json", dict(
        schema=SCHEMA, created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        cwd=str(cwd), platform=dict(system=platform.system(), node=platform.node()),
        python=sys.version.split()[0], commands=identities, git=git, cases=args.cases,
        expected_exit_code=args.expected_exit_code, repeat=args.repeat,
        compare_stderr=args.compare_stderr, timeout_seconds=args.timeout_seconds))

    results = []
    interrupted = False
    with (out_dir / "runs.jsonl").open("w", encoding="utf-8") as ledger:
        for index, case in enumerate(args.cases, start=1):
            sides = {}
            record: dict[str, Any] = dict(case=index, args=case)
            for label in LABELS:
                runs = []
                for attempt in range(1, args.repeat + 1):
                    argv = commands[label] + case
                    run = run_once(argv, args.timeout_seconds, out_dir, f"{index:03d}-{label}-{attempt}")
                    run.update(case=index, label=label, attempt=attempt, argv=argv)
                    ledger.write(json.dumps(run, sort_keys=True) + "\n")
                    runs.append(run)
                    if run["interrupted"]:
                        interrupted = True
                        break
                if interrupted:
                    break
                sides[label] = side_outcome(runs, args.expected_exit_code, args.compare_stderr)
                record[label] = dict(state=sides[label][0],
                                     exit_codes=sorted({run["exit_code"] for run in runs}, key=str),
                                     stdout_sha256=sorted({run["stdout_sha256"] for run in runs}))
            if interrupted:
                break
            record["verdict"] = verdict(sides)
            results.append(record)
            notes = [f"{label} {state}" for label, (state, _) in sides.items() if state != "stable"]
            if record["verdict"] == "differ":
                hashes = [record[label]["stdout_sha256"][0] for label in LABELS]
                notes = (["stderr differs"] if hashes[0] == hashes[1] else
                         [f"{label} stdout {digest[:12]}" for label, digest in zip(LABELS, hashes)])
            print(f"case {index} {json.dumps(case)}: {record['verdict']}"
                  + (f" ({'; '.join(notes)})" if notes else ""))

    identity_check = check_identity(cwd, identities, {}, [], git)
    write_json(out_dir / "identity-check.json", identity_check)
    for change in identity_check["changes"]:
        print(f"identity changed during the comparison: {change['subject']}", file=sys.stderr)
    complete = not interrupted and len(results) == len(args.cases)
    all_match = (complete and identity_check["valid"]
                 and all(result["verdict"] == "match" for result in results))
    write_json(out_dir / "summary.json", dict(all_match=all_match, complete=complete,
                                              identity_valid=identity_check["valid"], cases=results))
    if interrupted:
        print(f"Interrupted; partial evidence in {out_dir}", file=sys.stderr)
        return 130
    print(("All cases match." if all_match else "Not every case matches; see summary.json.")
          + f" Evidence: {out_dir}")
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())

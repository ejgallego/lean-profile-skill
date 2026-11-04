#!/usr/bin/env python3
"""Run baseline and candidate over several argument sets and compare their output bytes.

Nothing is timed. Each case appends its arguments to both commands, runs them
sequentially, and retains stdout, stderr, exit status and hashes. A case
matches when exit status and stdout bytes agree, and stderr too with
`--compare-stderr`. With `--repeat`, a side whose output varies between runs
is reported as unstable rather than compared. Exit 0 means every case matched.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from compare_commands import parse_command, resolve_executable, sha256_file, write_json

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


def run_once(argv: list[str], timeout: float | None) -> dict[str, Any]:
    """Run to completion; on timeout the whole process group is killed on POSIX."""
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=os.name == "posix")
    except OSError as error:
        return dict(exit_code=None, timed_out=False, launch_error=str(error), stdout=b"", stderr=b"")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        stdout, stderr = process.communicate()
        timed_out = True
    return dict(exit_code=None if timed_out else process.returncode, timed_out=timed_out,
                launch_error=None, stdout=stdout, stderr=stderr)


def side_outcome(runs: list[dict[str, Any]], compare_stderr: bool) -> tuple[str, tuple | None]:
    """Collapse one side's repeats into a fingerprint, or say why it has none."""
    if any(run["launch_error"] for run in runs):
        return "failed to launch", None
    if any(run["timed_out"] for run in runs):
        return "timed out", None
    prints = {(run["exit_code"], run["stdout_sha256"], run["stderr_sha256"] if compare_stderr else None)
              for run in runs}
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
    parser.add_argument("--repeat", type=int, default=1, help="runs per side per case")
    parser.add_argument("--compare-stderr", action="store_true",
                        help="also require identical stderr bytes")
    parser.add_argument("--timeout-seconds", type=float, help="limit for each run")
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    commands = {label: parse_command(getattr(args, label), f"--{label}") for label in LABELS}
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    out_dir = args.out_dir
    if out_dir.exists():
        parser.error(f"refusing to overwrite {out_dir}")
    cwd = Path.cwd()
    executables = {}
    for label, command in commands.items():
        path = resolve_executable(command, cwd)
        executables[label] = dict(path=str(path), sha256=sha256_file(path))
    out_dir.mkdir(parents=True)
    write_json(out_dir / "manifest.json", dict(
        schema=SCHEMA, created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        cwd=str(cwd), platform=dict(system=platform.system(), node=platform.node()),
        python=sys.version.split()[0], commands=commands, executables=executables,
        cases=args.cases, repeat=args.repeat, compare_stderr=args.compare_stderr,
        timeout_seconds=args.timeout_seconds))

    results = []
    with (out_dir / "runs.jsonl").open("w", encoding="utf-8") as ledger:
        for index, case in enumerate(args.cases, start=1):
            sides = {}
            record: dict[str, Any] = dict(case=index, args=case)
            for label in LABELS:
                runs = []
                for attempt in range(1, args.repeat + 1):
                    run = run_once(commands[label] + case, args.timeout_seconds)
                    stem = f"{index:03d}-{label}-{attempt}"
                    for stream in ("stdout", "stderr"):
                        (out_dir / f"{stem}.{stream}").write_bytes(run[stream])
                        run[f"{stream}_sha256"] = hashlib.sha256(run.pop(stream)).hexdigest()
                        run[stream] = f"{stem}.{stream}"
                    run.update(case=index, label=label, attempt=attempt, argv=commands[label] + case)
                    ledger.write(json.dumps(run, sort_keys=True) + "\n")
                    runs.append(run)
                sides[label] = side_outcome(runs, args.compare_stderr)
                record[label] = dict(state=sides[label][0],
                                     exit_codes=sorted({run["exit_code"] for run in runs}, key=str),
                                     stdout_sha256=sorted({run["stdout_sha256"] for run in runs}))
            record["verdict"] = verdict(sides)
            results.append(record)
            notes = [f"{label} {state}" for label, (state, _) in sides.items() if state != "stable"]
            if record["verdict"] == "differ":
                notes = [f"{label} exit {record[label]['exit_codes'][0]}, stdout "
                         f"{record[label]['stdout_sha256'][0][:12]}" for label in LABELS]
            print(f"case {index} {json.dumps(case)}: {record['verdict']}"
                  + (f" ({'; '.join(notes)})" if notes else ""))

    all_match = all(result["verdict"] == "match" for result in results)
    write_json(out_dir / "summary.json", dict(all_match=all_match, cases=results))
    print(("All cases match." if all_match else "Not every case matches; see summary.json.")
          + f" Evidence: {out_dir}")
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())

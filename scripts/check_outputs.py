#!/usr/bin/env python3
"""Compare retained compare_commands.py stdout with trusted bytes; never run commands.

The requested validation path is accompanied by a sibling `<stem>-results.json`
containing the byte-comparison evidence referenced from the validation record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from import_comparison import read_capture

CHECK_SCHEMA = "lean-profile-output-check-alpha"
VALIDATION_SCHEMA = "lean-profile-command-validation-alpha"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def dump(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def retained_stdout(capture, row):
    """Read a run's stdout, refusing anything outside the retained capture."""
    path = row.get("stdout")
    if not isinstance(path, str):
        raise ValueError(f'Run {row["sequence"]} records no stdout path')
    resolved = (capture / path).resolve()
    if not resolved.is_relative_to(capture.resolve()):
        raise ValueError(f'Run {row["sequence"]} stdout is outside the capture: {path}')
    return resolved.read_bytes()


def finished(row):
    """A run that did not finish has no complete output to compare."""
    for flag in ("timed_out", "interrupted"):
        if type(row.get(flag)) is not bool:
            raise ValueError(f"Run must record {flag}")
    return not (row["timed_out"] or row["interrupted"] or row.get("launch_error")
                or row.get("exit_code") is None)


def check_outputs(capture, expected, scope, out):
    """Write hash-bound records; a mismatch is recorded as failed, never dropped."""
    capture, expected, out = Path(capture).absolute(), Path(expected).absolute(), Path(out).absolute()
    evidence = out.with_name(out.stem + "-results.json")
    for path in (out, evidence):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    if not scope.strip():
        raise ValueError("Scope must state what the expected output establishes")
    _, rows, _, snapshots = read_capture(capture)
    trusted = expected.read_bytes()
    results, checks = [], []
    for row in rows:
        if not finished(row):
            continue
        stdout = retained_stdout(capture, row)
        matched = stdout == trusted
        results.append(dict(sequence=row["sequence"], stdout=row["stdout"],
                            stdout_sha256=sha256(stdout), matched=matched))
        checks.append(dict(sequence=row["sequence"], result="passed" if matched else "failed", scope=scope))
    if not results:
        raise ValueError("No completed runs to check")
    record = dict(schema=CHECK_SCHEMA, capture=str(capture), expected=str(expected),
                  expected_sha256=sha256(trusted), runs=results)
    raw = dump(record)
    for index, check in enumerate(checks):
        check["artifacts"] = [dict(path=evidence.name, sha256=sha256(raw), record=f"/runs/{index}")]
    validation = dict(schema=VALIDATION_SCHEMA, manifest_sha256=sha256(snapshots["source-manifest.json"]),
                      runs_sha256=sha256(snapshots["source-runs.jsonl"]), checks=checks)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: a concurrent writer fails here rather than being replaced.
    with evidence.open("xb") as stream:
        stream.write(raw)
    with out.open("xb") as stream:
        stream.write(dump(validation))
    return sum(run["matched"] for run in results), len(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Retained compare_commands.py output")
    parser.add_argument("--expected", type=Path, required=True,
                        help="Trusted stdout bytes, produced independently of the runs when possible")
    parser.add_argument("--scope", required=True, help="What matching this output establishes")
    parser.add_argument("--out", type=Path, required=True,
                        help="Fresh validation JSON; also writes sibling <stem>-results.json")
    args = parser.parse_args()
    matched, total = check_outputs(args.capture, args.expected, args.scope, args.out)
    print(f"{matched}/{total} completed runs matched; {args.out}")
    raise SystemExit(0 if matched == total else 1)

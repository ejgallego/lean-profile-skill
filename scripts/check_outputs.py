#!/usr/bin/env python3
"""Compare retained compare_commands.py stdout with trusted bytes; never run commands."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CHECK_SCHEMA = "lean-profile-output-check-alpha"
VALIDATION_SCHEMA = "lean-profile-command-validation-alpha"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def check_outputs(capture, expected, scope, out):
    """Write hash-bound records; a mismatch is recorded as failed, never dropped."""
    capture, expected, out = Path(capture).absolute(), Path(expected).absolute(), Path(out).absolute()
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite {out}")
    if not scope.strip():
        raise ValueError("Scope must state what the expected output establishes")
    manifest_raw = (capture / "manifest.json").read_bytes()
    runs_raw = (capture / "runs.jsonl").read_bytes()
    trusted = expected.read_bytes()
    results, checks = [], []
    evidence = out.with_name(out.stem + "-results.json")
    for line in runs_raw.decode().splitlines():
        row = json.loads(line)
        # A run that did not finish has no complete output to compare.
        if row["timed_out"] or row["interrupted"] or row["launch_error"] or row["exit_code"] is None:
            continue
        stdout = (capture / row["stdout"]).read_bytes()
        matched = stdout == trusted
        results.append(dict(sequence=row["sequence"], stdout=row["stdout"],
                            stdout_sha256=sha256(stdout), matched=matched))
        checks.append(dict(sequence=row["sequence"], result="passed" if matched else "failed", scope=scope))
    if not results:
        raise ValueError("No completed runs to check")
    record = dict(schema=CHECK_SCHEMA, capture=str(capture), expected=str(expected),
                  expected_sha256=sha256(trusted), runs=results)
    raw = (json.dumps(record, indent=2, allow_nan=False) + "\n").encode()
    for index, check in enumerate(checks):
        check["artifacts"] = [dict(path=evidence.name, sha256=sha256(raw), record=f"/runs/{index}")]
    out.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(raw)
    write_json(out, dict(schema=VALIDATION_SCHEMA, manifest_sha256=sha256(manifest_raw),
                         runs_sha256=sha256(runs_raw), checks=checks))
    return sum(run["matched"] for run in results), len(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Retained compare_commands.py output")
    parser.add_argument("--expected", type=Path, required=True,
                        help="Trusted stdout bytes, produced independently of the runs when possible")
    parser.add_argument("--scope", required=True, help="What matching this output establishes")
    parser.add_argument("--out", type=Path, required=True, help="Fresh validation record for --validation")
    args = parser.parse_args()
    matched, total = check_outputs(args.capture, args.expected, args.scope, args.out)
    print(f"{matched}/{total} completed runs matched; {args.out}")
    raise SystemExit(0 if matched == total else 1)

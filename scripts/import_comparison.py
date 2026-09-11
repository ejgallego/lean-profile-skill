#!/usr/bin/env python3
"""Import retained compare_commands.py evidence; never run benchmark commands."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex

from review_data import SCHEMA, array, digest, text
from review_observations import json_value, jsonl_rows, observations

CONFIGURATIONS = ("baseline", "candidate")


def read_capture(run_dir):
    """Read each source snapshot once and check capture identity structure."""
    manifest_raw = (run_dir / "manifest.json").read_bytes()
    runs_raw = (run_dir / "runs.jsonl").read_bytes()
    manifest = json_value(manifest_raw)
    if not isinstance(manifest, dict) or manifest.get("schema") != "lean-profile-compare-alpha":
        raise ValueError("Expected a compare_commands.py capture manifest")
    commands = manifest.get("commands", {})
    if not isinstance(commands, dict):
        raise ValueError("Capture commands must be an object")
    for name in CONFIGURATIONS:
        command = commands.get(name)
        argv = command.get("argv") if isinstance(command, dict) else None
        if not isinstance(argv, list) or not argv or any(not isinstance(s, str) for s in argv):
            raise ValueError(f"Missing exact argv for {name}")
    expected = manifest.get("expected_exit_code")
    if type(expected) is not int:
        raise ValueError("Capture must record expected_exit_code")
    rows = [row for _, row in jsonl_rows(runs_raw, run_dir / "runs.jsonl")]
    if not rows:
        raise ValueError("No retained observations")
    sequences = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get("sequence")) is not int or row["sequence"] < 1:
            raise ValueError("Run records require positive integer sequence IDs")
        if row["sequence"] in sequences:
            raise ValueError("Duplicate run sequence")
        sequences.add(row["sequence"])
    snapshots = {"source-manifest.json": manifest_raw, "source-runs.jsonl": runs_raw}
    identity_path = run_dir / "identity-check.json"
    identity_valid = False
    if identity_path.is_file():
        raw = identity_path.read_bytes()
        identity = json_value(raw)
        if (not isinstance(identity, dict)
                or identity.get("schema") != "lean-profile-identity-check-alpha"
                or type(identity.get("valid")) is not bool
                or not isinstance(identity.get("changes"), list)
                or (identity["valid"] and identity["changes"])):
            raise ValueError("Invalid identity-check record")
        identity_valid = identity["valid"]
        snapshots["source-identity.json"] = raw
    return manifest, rows, identity_valid, snapshots


def validation_records(validation, sequences, snapshots, out):
    """Bind checks to the capture, retaining selectors but sharing artifact reads."""
    if validation is None:
        return {}, []
    checks, links, hashes = {}, {}, {}
    validation = Path(validation).absolute()
    raw = validation.read_bytes()
    spec = json_value(raw)
    if not isinstance(spec, dict) or spec.get("schema") != "lean-profile-command-validation-alpha":
        raise ValueError("Unsupported command-validation record")
    for key, snapshot in (("runs_sha256", snapshots["source-runs.jsonl"]),
                          ("manifest_sha256", snapshots["source-manifest.json"])):
        if spec.get(key) != hashlib.sha256(snapshot).hexdigest():
            raise ValueError(f"Validation does not bind the captured {key}")
    validation_hash = hashlib.sha256(raw).hexdigest()
    snapshots["source-validation.json"] = raw
    for index, check in enumerate(array(spec, "checks")):
        if not isinstance(check, dict):
            raise ValueError("Validation checks must be objects")
        sequence = check.get("sequence")
        if type(sequence) is not int or sequence not in sequences or sequence in checks:
            raise ValueError("Unknown or duplicate validation sequence")
        if check.get("result") not in ("passed", "failed"):
            raise ValueError("Validation result must be passed or failed")
        scope = text(check, "scope")
        artifacts = array(check, "artifacts")
        if not artifacts:
            raise ValueError("Validation checks require hashed evidence artifacts")
        evidence = []
        for artifact in artifacts:
            path = (validation.parent / text(artifact, "path")).absolute()
            expected_hash = text(artifact, "sha256")
            if path not in hashes:
                if not path.is_file():
                    raise ValueError(f"Validation artifact missing: {path}")
                hashes[path] = digest(path)
            if hashes[path] != expected_hash:
                raise ValueError(f"Validation artifact missing or changed: {path}")
            evidence.append(dict(path=str(path), sha256=expected_hash,
                                 record=text(artifact, "record")))
            links.setdefault(path, dict(title=f"Validation evidence: {path.name}", path=str(path)))
        checks[sequence] = dict(result=check["result"], scope=scope, artifacts=evidence,
                                artifact=str(out / "source-validation.json"),
                                sha256=validation_hash, record=f"/checks/{index}")
    return checks, list(links.values())


def normalize_run(row, manifest, check, identity_valid, run_dir):
    """Describe one retained outcome; never infer correctness from exit status."""
    name = row.get("label")
    if not isinstance(name, str) or name not in CONFIGURATIONS:
        raise ValueError("Unknown command label")
    if row.get("argv") != manifest["commands"][name]["argv"]:
        raise ValueError("Run argv disagrees with the source manifest")
    if row.get("phase") not in ("warmup", "measured"):
        raise ValueError("Run must record warmup or measured phase")
    if type(row.get("elapsed_ns")) is not int:
        raise ValueError("Run must record integer elapsed_ns")
    for flag in ("timed_out", "interrupted"):
        if type(row.get(flag)) is not bool:
            raise ValueError(f"Run must record {flag}")
    for key in ("pass", "slot"):
        if type(row.get(key)) is not int or row[key] < 1:
            raise ValueError(f"Run must record positive {key}")
    for key in ("launch_error", "evidence_error", "exit_code"):
        if key not in row:
            raise ValueError(f"Run must record {key}")
    for key in ("launch_error", "evidence_error"):
        if row[key] is not None and (not isinstance(row[key], str) or not row[key].strip()):
            raise ValueError(f"Run {key} must be null or nonempty text")
    outcome = ("timeout" if row["timed_out"] else
               "interrupted" if row["interrupted"] else
               "error" if row["launch_error"] is not None else "completed")
    validated = check is not None and check["result"] == "passed"
    reasons = []
    if row.get("phase") == "warmup":
        reasons.append("warmup")
    if outcome != "completed":
        reasons.append(outcome)
    elif row["exit_code"] != manifest["expected_exit_code"]:
        reasons.append("unexpected exit status")
    if row["evidence_error"]:
        reasons.append("harness evidence check failed")
    if not identity_valid:
        reasons.append("missing or failed capture identity check")
    if not validated:
        reasons.append("output validation failed" if check else "no output-validation record")
    record = dict(
        row, id=f'{row["phase"]}/{row["pass"]}/{name}', configuration=name,
        block=str(row["pass"]), outcome=outcome, exit_status=row["exit_code"],
        validated=validated, included=not reasons, exclude_reason="; ".join(reasons),
        capture_directory=str(run_dir),
    )
    if check:
        record["validation"] = check
    if outcome == "timeout":
        record["timeout_s"] = manifest.get("timeout_seconds")
    return record


def report_manifest(manifest, title, boundary, cohort, links):
    # Exact argv is readable without discarding array-valued records in JSONL.
    command = "\n".join(f"{name}: {shlex.join(manifest['commands'][name]['argv'])}" for name in CONFIGURATIONS)
    note = ("Imported retained evidence; no commands executed. Missing output checks leave runs "
            "visible but excluded. Elapsed readings include harness overhead and, on timeout, "
            "termination handling; the configured limit is a separate value.")
    if manifest.get("perf"):
        note += " This capture includes perf-stat overhead; it is instrumented evidence."
    return dict(
        schema=SCHEMA, title=title, summary=note,
        datasets=[dict(id="commands", title=title, configurations=list(CONFIGURATIONS),
                       samples="observations.jsonl", boundary=boundary, cohort=cohort,
                       identity="Source manifest and identity-check records linked below",
                       command=command, expected_exit_status=manifest["expected_exit_code"])],
        baselines=[dict(id=f"base-{name}", title=f"{name}: recorded outcomes",
                        dataset="commands", configuration=name, note=note) for name in CONFIGURATIONS],
        comparisons=[dict(id="comparison", title=title, dataset="commands",
                          control="baseline", candidate="candidate", decision="Not assessed by the importer",
                          note=note)],
        links=links,
    )


def import_comparison(run_dir, out, *, boundary, cohort, title="Command comparison",
                      validation=None):
    run_dir, out = Path(run_dir).absolute(), Path(out).absolute()
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite {out}")
    for value in (boundary, cohort, title):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Title, boundary and cohort must be explicit nonempty text")
    manifest, rows, identity_valid, snapshots = read_capture(run_dir)
    checks, links = validation_records(
        validation, {row["sequence"] for row in rows}, snapshots, out,
    )
    normalized = [normalize_run(row, manifest, checks.get(row["sequence"]), identity_valid, run_dir)
                  for row in rows]
    snapshot = b"".join((json.dumps(row, allow_nan=False) + "\n").encode() for row in normalized)
    # Exercise the report's validation before creating any output.
    observations(snapshot, CONFIGURATIONS, format="jsonl",
                 expected_exit_status=manifest["expected_exit_code"], boundary=boundary, cohort=cohort)
    snapshots["observations.jsonl"] = snapshot
    links = [dict(title=name, path=name) for name in snapshots if name != "observations.jsonl"] + links
    report = report_manifest(manifest, title, boundary, cohort, links)
    out.mkdir(parents=True)
    for name, raw in snapshots.items():
        (out / name).write_bytes(raw)
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return out / "report.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Retained compare_commands.py output")
    parser.add_argument("--out", type=Path, required=True, help="Fresh import directory")
    parser.add_argument("--boundary", required=True, help="Actual timing boundary, including harness overhead")
    parser.add_argument("--cohort", required=True, help="Workload/cache conditions")
    parser.add_argument("--title", default="Command comparison")
    parser.add_argument("--validation", type=Path, help="Explicit hash-bound output-validation records")
    args = parser.parse_args()
    print(import_comparison(args.run_dir, args.out, boundary=args.boundary,
                            cohort=args.cohort, title=args.title, validation=args.validation))

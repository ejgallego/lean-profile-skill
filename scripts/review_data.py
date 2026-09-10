#!/usr/bin/env python3
"""Validated, explicitly included performance observations for report consumers.

AI-generated from the SF-in-Lean investigation; no measurement commands run here.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
from pathlib import Path


def stats(values):
    """Inclusive, linearly interpolated quartiles; single diagnostics are valid."""
    values = sorted(values)
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError("Statistics require nonempty finite observations")

    def quantile(p):
        index = (len(values) - 1) * p
        lo, hi = math.floor(index), math.ceil(index)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)

    q1, q3 = quantile(0.25), quantile(0.75)
    result = dict(
        n=len(values),
        median=statistics.median(values),
        q1=q1,
        q3=q3,
        iqr=q3 - q1,
        min=values[0],
        max=values[-1],
    )
    if not all(math.isfinite(value) for value in result.values()):
        raise ValueError("Statistics overflowed; check the input units and values")
    return result


def reduction(before, after):
    result = 100 * (1 - after / before)
    if not math.isfinite(result):
        raise ValueError("Median ratio overflowed; check the input units and values")
    return result


def observations(raw, configurations, source="CSV"):
    """Parse one CSV snapshot, retaining exclusion provenance and original IDs."""
    if len(set(configurations)) != len(configurations):
        raise ValueError("Configurations must differ")
    groups = {name: {} for name in configurations}
    excluded = []
    required = {
        "configuration",
        "pair",
        "wall_s",
        "exit_status",
        "phase",
        "validated",
        "accepted",
        "exclude_reason",
    }
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    fields = reader.fieldnames or []
    if not required <= set(fields) or len(fields) != len(set(fields)):
        raise ValueError(
            f"{source}: require unique columns including {sorted(required)}"
        )
    resources = [k for k in ("user_s", "system_s", "peak_rss_kib") if k in fields]
    for line, row in enumerate(reader, 2):
        prefix = f"{source}:{line}"
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"{prefix}: wrong number of CSV fields")
        if row["phase"] not in {"measured", "warmup"}:
            raise ValueError(f"{prefix}: invalid phase")
        if any(row[k] not in {"true", "false"} for k in ("accepted", "validated")):
            raise ValueError(f"{prefix}: booleans must be true/false")
        if row["configuration"] not in groups:
            raise ValueError(f"{prefix}: unexpected configuration")
        if row["phase"] == "warmup" or row["accepted"] == "false":
            if row["phase"] == "measured" and not row["exclude_reason"].strip():
                raise ValueError(f"{prefix}: exclusion needs a reason")
            excluded.append(
                dict(
                    line=line,
                    configuration=row["configuration"],
                    pair=row["pair"],
                    phase=row["phase"],
                    reason=row["exclude_reason"],
                )
            )
            continue
        if row["exit_status"] != "0" or row["validated"] != "true":
            raise ValueError(f"{prefix}: accepted sample failed exit/output validation")
        numbers = {}
        for key in ["wall_s"] + resources:
            try:
                value = float(row[key])
            except ValueError as error:
                raise ValueError(f"{prefix}: invalid {key}") from error
            if (
                not math.isfinite(value)
                or value < 0
                or (key == "wall_s" and value == 0)
            ):
                raise ValueError(
                    f"{prefix}: invalid {key}: require finite nonnegative resources and positive wall"
                )
            numbers[key] = value
        pair = row["pair"]
        group = groups[row["configuration"]]
        if not pair.strip() or pair in group:
            raise ValueError(f"{prefix}: missing or duplicate included pair")
        group[pair] = numbers
    if any(not group for group in groups.values()):
        raise ValueError(f"{source}: no included observations")
    return groups, excluded


def series(group):
    return dict(
        statistics={
            key: stats([row[key] for row in group.values()])
            for key in next(iter(group.values()))
        },
        observation_ids=list(group),
        observations=list(group.values()),
    )


def paired(groups, control, candidate, excluded):
    a, b = groups[control], groups[candidate]
    if a.keys() != b.keys():
        raise ValueError(
            "Require complete matched pairs; exclude both members explicitly"
        )
    savings = [a[pair]["wall_s"] - b[pair]["wall_s"] for pair in a]
    before, after = series(a), series(b)
    return dict(
        control=before["statistics"]["wall_s"],
        candidate=after["statistics"]["wall_s"],
        paired_saving_s=stats(savings),
        candidate_faster=sum(v > 0 for v in savings),
        pair_ids=list(a),
        savings=savings,
        excluded=excluded,
        median_reduction_pct=reduction(
            before["statistics"]["wall_s"]["median"],
            after["statistics"]["wall_s"]["median"],
        ),
        series={"control": before, "candidate": after},
    )


def summarize(path, control, candidate):
    groups, excluded = observations(Path(path).read_bytes(), [control, candidate], path)
    return paired(groups, control, candidate, excluded)


def text(obj, key):
    if not isinstance(obj, dict):
        raise ValueError("Expected an object")
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing text: {key}")
    return value


def array(obj, key):
    if not isinstance(obj, dict):
        raise ValueError("Expected an object")
    value = obj.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    return value


def load(manifest_path):
    """Normalize a v1 manifest; profiles stay linked and CSV bytes are snapshotted.

    Returns the serializable model, original manifest bytes, and named CSV copies.
    Historical endpoints reference measured series without manufacturing pairing.
    """
    manifest_path = Path(manifest_path).absolute()
    raw = manifest_path.read_bytes()

    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Nonfinite JSON number: {value}")
        return number

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    spec = json.loads(
        raw,
        parse_constant=reject_constant,
        parse_float=finite_number,
        object_pairs_hook=unique_keys,
    )
    if not isinstance(spec, dict) or spec.get("schema") != "lean-profile-review-v1":
        raise ValueError("Unsupported review schema")
    model = dict(
        schema=spec["schema"],
        title=text(spec, "title"),
        summary=text(spec, "summary"),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        quartiles="inclusive / linear interpolation",
        baselines=[],
        comparisons=[],
        profiles=[],
        links=[],
        attribution=[],
    )
    copies = []
    ids = {
        "baselines",
        "progress",
        "attribution",
        "measurements",
        "evidence",
        "filter",
        "count",
        "toast",
    }

    def identifier(item, default):
        value = item.get("id", default)
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value)
            or value in ids
            or value.startswith("frame-")
        ):
            raise ValueError(f"Invalid or duplicate ID: {value}")
        ids.add(value)
        return value

    def artifact(value):
        if not isinstance(value, str) or not value:
            raise ValueError("Artifact path must be a nonempty string")
        # Preserve symlink mount paths for an HTTP server rooted above the report.
        path = (manifest_path.parent / value).absolute()
        if not path.is_file():
            raise ValueError(f"Artifact must exist: {path}")
        return path

    for kind in ("baselines", "comparisons"):
        for index, item in enumerate(array(spec, kind)):
            if not isinstance(item, dict):
                raise ValueError(f"{kind} entries must be objects")
            for key in ("title", "boundary", "cohort", "identity", "command", "note"):
                text(item, key)
            is_base = kind == "baselines"
            keys = ["configuration"] if is_base else ["control", "candidate"]
            configurations = [text(item, key) for key in keys]
            if not is_base:
                text(item, "decision")
            source = artifact(item.get("samples"))
            snapshot = source.read_bytes()
            groups, excluded = observations(snapshot, configurations, source)
            name = f"baseline-{index:02}.csv" if is_base else f"samples-{index:02}.csv"
            entry = dict(
                item,
                id=identifier(
                    item, f"base-{index:02}" if is_base else f"cmp-{index:02}"
                ),
                samples_sha256=hashlib.sha256(snapshot).hexdigest(),
                copied_samples=name,
            )
            if is_base:
                entry.update(
                    series=series(groups[configurations[0]]), excluded=excluded
                )
            else:
                entry["statistics"] = paired(groups, *configurations, excluded)
            model[kind].append(entry)
            copies.append((name, snapshot))
    comparison_ids = {c["id"] for c in model["comparisons"]}
    for index, item in enumerate(array(spec, "profiles")):
        for key in ("title", "boundary", "identity", "note"):
            text(item, key)
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in {
            "perfetto",
            "viewer",
            "image",
            "raw",
        }:
            raise ValueError(f"Unknown profile kind: {kind}")
        if "comparison" in item and (
            not isinstance(item["comparison"], str)
            or item["comparison"] not in comparison_ids
        ):
            raise ValueError("Profile references an unknown comparison")
        source = artifact(item.get("path"))
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        model["profiles"].append(
            dict(
                item,
                id=identifier(item, f"profile-{index:02}"),
                artifact_path=str(source),
                sha256=digest.hexdigest(),
            )
        )
    for item in array(spec, "links"):
        model["links"].append(
            dict(
                title=text(item, "title"), artifact_path=str(artifact(item.get("path")))
            )
        )
    for item in array(spec, "attribution"):
        model["attribution"].append(
            dict(title=text(item, "title"), text=text(item, "text"))
        )
    if "progress" in spec:
        progress = spec["progress"]
        model["progress"] = dict(
            note=text(progress, "note"), selected=[], totals=[], historical=[]
        )
        comparisons = {c["id"]: c for c in model["comparisons"]}
        baselines = {b["id"]: b for b in model["baselines"]}
        for key in ("selected", "totals"):
            for cid in array(progress, key):
                if (
                    not isinstance(cid, str)
                    or cid not in comparisons
                    or cid in model["progress"][key]
                ):
                    raise ValueError(f"Unknown or duplicate progress comparison: {cid}")
                model["progress"][key].append(cid)

        def endpoint(ref):
            if not isinstance(ref, dict):
                raise ValueError("Historical endpoint must reference a measured series")
            if (
                set(ref) == {"baseline"}
                and isinstance(ref["baseline"], str)
                and ref["baseline"] in baselines
            ):
                record = baselines[ref["baseline"]]
                distribution = record["series"]["statistics"]["wall_s"]
                configuration = record["configuration"]
            elif (
                set(ref) == {"comparison", "side"}
                and isinstance(ref["comparison"], str)
                and ref["comparison"] in comparisons
                and isinstance(ref["side"], str)
                and ref["side"] in {"control", "candidate"}
            ):
                record = comparisons[ref["comparison"]]
                distribution = record["statistics"][ref["side"]]
                configuration = record[ref["side"]]
            else:
                raise ValueError("Invalid historical endpoint reference")
            return dict(
                reference=ref,
                statistics=distribution,
                configuration=configuration,
                identity=record["identity"],
                command=record["command"],
                boundary=record["boundary"],
                cohort=record["cohort"],
                samples_sha256=record["samples_sha256"],
            )

        for item in array(progress, "historical"):
            if not isinstance(item, dict):
                raise ValueError("Historical entries must be objects")
            a, b = endpoint(item.get("from")), endpoint(item.get("to"))
            if a["command"] != b["command"] or a["boundary"] != b["boundary"]:
                raise ValueError(
                    "Historical endpoints must name the same command and timing boundary"
                )
            model["progress"]["historical"].append(
                dict(
                    kind="historical_unpaired",
                    title=text(item, "title"),
                    note=text(item, "note"),
                    before=a,
                    after=b,
                    median_reduction_pct=reduction(
                        a["statistics"]["median"], b["statistics"]["median"]
                    ),
                )
            )
    return model, raw, copies

"""Load explicit datasets and contrasts from an alpha performance-review manifest."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from review_observations import json_value, observations, paired, reduction, series

SCHEMA = "lean-profile-review-alpha"
METADATA = ("boundary", "cohort", "identity", "command")


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


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def load(manifest_path):
    """Return the derived model, original manifest bytes and dataset snapshots.

    Each dataset is parsed/hashed/copied once, regardless of how many baselines
    or contrasts refer to it. Linked evidence remains external, not bundled.
    """
    manifest_path = Path(manifest_path).absolute()
    raw = manifest_path.read_bytes()
    spec = json_value(raw)
    if not isinstance(spec, dict) or spec.get("schema") != SCHEMA:
        raise ValueError(f"Unsupported review schema; expected {SCHEMA}")
    model = dict(
        schema=SCHEMA, title=text(spec, "title"), summary=text(spec, "summary"),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        quartiles="inclusive / linear interpolation", datasets=[], baselines=[],
        comparisons=[], profiles=[], links=[], attribution=[],
    )
    copies = []
    ids = {"baselines", "datasets", "progress", "attribution", "measurements",
           "evidence", "filter", "decision-filter", "count", "toast"}

    def identifier(item, default=None):
        value = item.get("id", default)
        if (not isinstance(value, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value)
                or value in ids or value.startswith("frame-")):
            raise ValueError(f"Invalid or duplicate ID: {value}")
        ids.add(value)
        return value

    def artifact(value):
        if not isinstance(value, str) or not value:
            raise ValueError("Artifact path must be a nonempty string")
        # Keep symlink mount paths reachable under a common HTTP server root.
        path = (manifest_path.parent / value).absolute()
        if not path.is_file():
            raise ValueError(f"Artifact must exist: {path}")
        return path

    hashes = {}

    def artifact_hash(path):
        if path not in hashes:
            hashes[path] = digest(path)
        return hashes[path]

    datasets = {}
    for index, item in enumerate(array(spec, "datasets")):
        entry = {key: text(item, key) for key in METADATA}
        entry.update(id=identifier(item), title=text(item, "title"))
        configurations = array(item, "configurations")
        source = artifact(item.get("samples"))
        format = item.get("format", source.suffix.lstrip("."))
        snapshot = source.read_bytes()
        parsed = observations(
            snapshot, configurations, source, format=format,
            expected_exit_status=item.get("expected_exit_status", 0),
            boundary=entry["boundary"], cohort=entry["cohort"],
        )
        name = f"dataset-{index:02}.{format}"
        entry.update(
            configurations=configurations, samples=item["samples"], format=format,
            samples_sha256=hashlib.sha256(snapshot).hexdigest(), copied_samples=name,
            expected_exit_status=item.get("expected_exit_status", 0),
            series={name: series(rows) for name, rows in parsed.items()},
        )
        model["datasets"].append(entry)
        datasets[entry["id"]] = entry
        copies.append((name, snapshot))

    for kind in ("baselines", "comparisons"):
        for index, item in enumerate(array(spec, kind)):
            entry = dict(title=text(item, "title"), note=text(item, "note"))
            dataset_id = text(item, "dataset")
            if dataset_id not in datasets:
                raise ValueError(f"Unknown dataset: {dataset_id}")
            if any(key in item for key in (*METADATA, "samples", "configurations")):
                raise ValueError("Measurement metadata belongs to the referenced dataset, not an individual contrast")
            dataset = datasets[dataset_id]
            is_base = kind == "baselines"
            entry.update({k: dataset[k] for k in (*METADATA, "samples_sha256", "copied_samples")})
            entry.update(dataset=dataset_id, id=identifier(
                item, f"base-{index:02}" if is_base else f"cmp-{index:02}"))
            for key in (["configuration"] if is_base else ["control", "candidate"]):
                entry[key] = text(item, key)
                if entry[key] not in dataset["configurations"]:
                    raise ValueError(f"Unknown configuration: {entry[key]}")
            if is_base:
                entry["series"] = dataset["series"][entry["configuration"]]
                entry["excluded"] = entry["series"]["excluded"]
            else:
                entry["decision"] = text(item, "decision")
                status = item.get("decision_status")
                if status is not None and status not in ("accepted", "rejected", "inconclusive"):
                    raise ValueError("decision_status must be accepted, rejected or inconclusive")
                entry["decision_status"] = status
                if "group" in item:
                    entry["group"] = text(item, "group")
                entry["statistics"] = paired(dataset["series"], entry["control"], entry["candidate"])
            model[kind].append(entry)

    groups = {}
    for entry in model["comparisons"]:
        if "group" in entry:
            shared = tuple(entry[key] for key in ("note", "decision", "decision_status"))
            prior = groups.setdefault(entry["group"], shared)
            if prior != shared:
                raise ValueError("Grouped comparisons must share note, decision and decision_status; datasets remain separate")

    comparison_ids = {c["id"] for c in model["comparisons"]}
    for index, item in enumerate(array(spec, "profiles")):
        entry = {key: text(item, key) for key in ("title", "boundary", "identity", "note")}
        kind = item.get("kind")
        if kind not in ("perfetto", "viewer", "image", "raw"):
            raise ValueError(f"Unknown profile kind: {kind}")
        if "comparison" in item:
            comparison = text(item, "comparison")
            if comparison not in comparison_ids:
                raise ValueError("Profile references an unknown comparison")
            entry["comparison"] = comparison
        source = artifact(item.get("path"))
        entry.update(kind=kind, id=identifier(item, f"profile-{index:02}"),
                     artifact_path=str(source), sha256=artifact_hash(source))
        model["profiles"].append(entry)
    seen_links = set()
    for item in array(spec, "links"):
        title = text(item, "title")
        source = artifact(item.get("path"))
        # Preserve distinct annotations while suppressing exact duplicate links.
        if (source, title) not in seen_links:
            model["links"].append(dict(title=title, artifact_path=str(source), sha256=artifact_hash(source)))
            seen_links.add((source, title))
    for item in array(spec, "attribution"):
        model["attribution"].append(dict(title=text(item, "title"), text=text(item, "text")))

    if "progress" in spec:
        progress = spec["progress"]
        model["progress"] = dict(note=text(progress, "note"), selected=[], totals=[], historical=[])
        comparisons = {c["id"]: c for c in model["comparisons"]}
        baselines = {b["id"]: b for b in model["baselines"]}
        for key in ("selected", "totals"):
            for cid in array(progress, key):
                if (not isinstance(cid, str) or cid not in comparisons
                        or cid in model["progress"][key]):
                    raise ValueError(f"Unknown or duplicate progress comparison: {cid}")
                model["progress"][key].append(cid)

        def endpoint(ref):
            if not isinstance(ref, dict):
                raise ValueError("Historical endpoint must reference a recorded series")
            if (set(ref) == {"baseline"} and isinstance(ref["baseline"], str)
                    and ref["baseline"] in baselines):
                record = baselines[ref["baseline"]]
                values = record["series"]
                configuration = record["configuration"]
            elif (set(ref) == {"comparison", "side"}
                  and isinstance(ref["comparison"], str) and ref["comparison"] in comparisons
                  and ref["side"] in ("control", "candidate")):
                record = comparisons[ref["comparison"]]
                values = record["statistics"]["series"][ref["side"]]
                configuration = record[ref["side"]]
            else:
                raise ValueError("Invalid historical endpoint reference")
            return dict(reference=ref, statistics=values["statistics"].get("wall_s"),
                        censored=values["censored"], configuration=configuration,
                        **{k: record[k] for k in (*METADATA, "samples_sha256")})

        for item in array(progress, "historical"):
            title, note = text(item, "title"), text(item, "note")
            a, b = endpoint(item.get("from")), endpoint(item.get("to"))
            if a["command"] != b["command"] or a["boundary"] != b["boundary"]:
                raise ValueError("Historical endpoints must name the same command and timing boundary")
            usable = a["statistics"] and b["statistics"] and not (a["censored"] or b["censored"])
            model["progress"]["historical"].append(dict(
                kind="historical_unpaired", title=title, note=note, before=a, after=b,
                median_reduction_pct=(reduction(a["statistics"]["median"], b["statistics"]["median"])
                                      if usable else None),
            ))
    return model, raw, copies

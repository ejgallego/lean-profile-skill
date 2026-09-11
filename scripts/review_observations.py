"""Shared CSV/JSONL observations, outcome accounting and explicit paired contrasts."""

from __future__ import annotations

import csv
import io
import json
import math
import statistics

REQUIRED_FIELDS = {"id", "configuration", "block", "phase", "outcome", "exit_status",
                   "validated", "included", "exclude_reason"}


def json_value(raw):
    def constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"Nonfinite JSON number: {value}")
        return result

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=constant, parse_float=number,
                      object_pairs_hook=unique)


def stats(values):
    """Inclusive, linearly interpolated quartiles; no uncertainty estimate."""
    values = sorted(values)
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError("Statistics require nonempty finite observations")

    def quantile(p):
        index = (len(values) - 1) * p
        lo, hi = math.floor(index), math.ceil(index)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)

    q1, q3 = quantile(.25), quantile(.75)
    result = dict(n=len(values), median=statistics.median(values), q1=q1, q3=q3,
                  iqr=q3 - q1, min=values[0], max=values[-1])
    if not all(math.isfinite(v) for v in result.values()):
        raise ValueError("Statistics overflowed; check the input units and values")
    return result


def decode_snapshot(raw, source):
    """Decode either observation format without losing source context on errors."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{source}: invalid UTF-8: {error}") from error


def csv_rows(raw, source):
    """Yield strict CSV records with their starting physical line numbers."""
    reader = csv.reader(io.StringIO(decode_snapshot(raw, source), newline=""), strict=True)
    try:
        fields = next(reader, [])
        if not REQUIRED_FIELDS <= set(fields) or len(fields) != len(set(fields)):
            raise ValueError(f"{source}: require unique columns including {sorted(REQUIRED_FIELDS)}")
        while True:
            line = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if not values:  # Empty physical lines are not observation records.
                continue
            if len(values) != len(fields):
                raise ValueError(f"{source}:{line}: wrong number of CSV fields")
            yield line, dict(zip(fields, values))
    except csv.Error as error:
        raise ValueError(f"{source}:{reader.line_num}: invalid CSV: {error}") from error


def jsonl_rows(raw, source):
    """Parse a JSONL snapshot with physical file locations, including blank lines."""
    for line, value in enumerate(decode_snapshot(raw, source).split("\n"), 1):
        if not value.strip():
            continue
        try:
            row = json_value(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{source}:{line}:{error.colno}: {error.msg}") from error
        except ValueError as error:
            raise ValueError(f"{source}:{line}: {error}") from error
        yield line, row


def reduction(before, after):
    result = 100 * (1 - after / before)
    if not math.isfinite(result):
        raise ValueError("Median ratio overflowed; check the input units and values")
    return result


def observations(raw, configurations, source="observations", *, format="csv",
                 expected_exit_status=0, boundary=None, cohort=None):
    """Parse a byte snapshot once. Preserve order, block IDs and all outcomes.

    JSONL keeps typed/nested fields and integer elapsed_ns. CSV is a flat input,
    not an export that round-trips arbitrary JSON structures.
    """
    if (not configurations or any(not isinstance(c, str) or not c.strip()
                                  for c in configurations)
            or len(set(configurations)) != len(configurations)):
        raise ValueError("Configurations must be nonempty, unique names")
    if type(expected_exit_status) is not int:
        raise ValueError("expected_exit_status must be an integer")
    if format == "csv":
        inputs = csv_rows(raw, source)
    elif format == "jsonl":
        inputs = jsonl_rows(raw, source)
    else:
        raise ValueError("Observation format must be csv or jsonl")
    groups = {name: [] for name in configurations}
    ids, blocks, slots = set(), set(), set()
    for line, row in inputs:
        prefix = f"{source}:{line}"

        def fail(message):
            raise ValueError(f"{prefix}: {message}")

        if not isinstance(row, dict) or not REQUIRED_FIELDS <= row.keys():
            fail("missing required observation fields")
        if "accepted" in row:
            fail("use included for statistical inclusion; accepted is a decision")
        for key in ("id", "configuration", "block", "phase", "outcome"):
            if not isinstance(row[key], str) or not row[key].strip():
                fail(f"{key} must be nonempty text")
        if not isinstance(row["exclude_reason"], str):
            fail("exclude_reason must be text")
        if row["configuration"] not in groups:
            fail("unexpected configuration")
        if row["phase"] not in {"measured", "warmup"}:
            fail("invalid phase")
        if row["outcome"] not in {"completed", "timeout", "interrupted", "error"}:
            fail("invalid outcome")
        for key, expected in (("boundary", boundary), ("cohort", cohort)):
            if key in row and expected is not None and row[key] != expected:
                fail(f"{key} disagrees with the dataset")
        record = dict(row, line=line)
        for key in ("validated", "included"):
            value = row[key]
            if format == "csv":
                if value not in {"true", "false"}:
                    fail(f"{key} must be true/false")
                value = value == "true"
            elif type(value) is not bool:
                fail(f"{key} must be a JSON boolean")
            record[key] = value

        def integer(key, optional=False):
            value = row.get(key)
            if optional and (value is None or value == ""):
                return None
            if format == "csv":
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    fail(f"{key} must be an integer")
            if type(value) is not int:
                fail(f"{key} must be an integer")
            return value

        def numeric(key, positive=False):
            value = row[key]
            if isinstance(value, bool):
                fail(f"invalid {key}")
            try:
                value = float(value)
            except (ValueError, TypeError, OverflowError):
                fail(f"invalid {key}")
            if not math.isfinite(value) or value < 0 or (positive and value == 0):
                fail(f"{key} must be finite and {'positive' if positive else 'nonnegative'}")
            return value

        record["exit_status"] = integer("exit_status", optional=True)
        if row["outcome"] == "completed" and record["exit_status"] is None:
            fail("completed outcomes require exit_status")
        elapsed = integer("elapsed_ns", optional=True)
        if elapsed is not None:
            try:
                seconds = elapsed / 1_000_000_000
            except OverflowError:
                fail("invalid elapsed_ns")
            if elapsed < 0 or not math.isfinite(seconds):
                fail("invalid elapsed_ns")
            if row.get("wall_s") not in (None, ""):
                fail("provide elapsed_ns or wall_s, not both")
            record["elapsed_ns"] = elapsed
            record["wall_s"] = seconds
        elif row.get("wall_s") not in (None, ""):
            record["wall_s"] = numeric("wall_s")
        else:
            record["wall_s"] = None
        if row["outcome"] == "completed" and record["wall_s"] is None:
            fail("completed outcomes require elapsed_ns or wall_s")
        if row["outcome"] == "timeout":
            if "timeout_s" not in row:
                fail("timeout outcomes require the configured timeout_s")
            record["timeout_s"] = numeric("timeout_s", positive=True)
        for key in ("user_s", "system_s", "peak_rss_kib"):
            if row.get(key) not in (None, ""):
                record[key] = numeric(key)
            else:
                record.pop(key, None)
        if record["included"]:
            if (row["phase"] != "measured" or row["outcome"] != "completed"
                    or not record["validated"]
                    or record["exit_status"] != expected_exit_status
                    or not record["wall_s"] or record["exclude_reason"].strip()):
                fail("included observations require a validated, positive measured completion, expected exit status and no exclusion reason")
        elif row["phase"] == "measured" and not row["exclude_reason"].strip():
            fail("excluded measured observations need a reason")
        block = (row["configuration"], row["phase"], row["block"])
        if row["id"] in ids or block in blocks:
            fail("duplicate observation ID or configuration/phase/block")
        ids.add(row["id"])
        blocks.add(block)
        slot = integer("slot", optional=True)
        if slot is not None:
            key = (row["phase"], row["block"], slot)
            if slot < 1 or key in slots:
                fail("slot must be positive and unique within a phase/block")
            slots.add(key)
            record["slot"] = slot
        groups[row["configuration"]].append(record)
    if not ids:
        raise ValueError(f"{source}: empty observation dataset")
    return groups


def series(rows):
    included = [row for row in rows if row["included"]]
    keys = ["wall_s", "user_s", "system_s", "peak_rss_kib"]
    # Missing resource values are not silently summarized over a smaller cohort.
    for key in keys[1:]:
        if any(key in r for r in included) and not all(key in r for r in included):
            raise ValueError(f"Included resource {key} must cover every observation")
    return dict(
        statistics={k: stats([r[k] for r in included]) for k in keys
                    if included and k in included[0]},
        observation_ids=[r["id"] for r in included],
        block_ids=[r["block"] for r in included],
        observations=included,
        outcomes=rows,
        excluded=[r for r in rows if not r["included"]],
        censored=any(r["phase"] == "measured" and r["outcome"] == "timeout" for r in rows),
    )


def paired(series_by_config, control, candidate):
    """Contrast precomputed configuration series; do not resummarize captures."""
    if control == candidate:
        raise ValueError("Control and candidate must differ")
    before, after = series_by_config[control], series_by_config[candidate]
    a = {r["block"]: r["wall_s"] for r in before["observations"]}
    b = {r["block"]: r["wall_s"] for r in after["observations"]}
    reason = ""
    if before["censored"] or after["censored"]:
        reason = "Measured timeouts: completed-only distributions are conditional; no paired or overall speedup is estimated."
    elif a.keys() != b.keys():
        reason = "Incomplete included blocks: no paired estimate. Review missing outcomes and explicitly exclude unmatched members if justified."
    elif not a:
        reason = "No included measured pairs. Recorded outcomes are not a timing baseline."
    savings = [] if reason else [a[block] - b[block] for block in a]
    return dict(
        control=before["statistics"].get("wall_s"),
        candidate=after["statistics"].get("wall_s"),
        paired_saving_s=stats(savings) if savings else None,
        candidate_faster=sum(v > 0 for v in savings) if savings else None,
        pair_ids=list(a) if savings else [], savings=savings,
        unmatched_blocks=dict(control=sorted(a.keys() - b.keys()),
                              candidate=sorted(b.keys() - a.keys())),
        excluded=before["excluded"] + after["excluded"],
        unavailable_reason=reason,
        median_reduction_pct=(reduction(before["statistics"]["wall_s"]["median"],
                                        after["statistics"]["wall_s"]["median"])
                              if savings else None),
        series=dict(control=before, candidate=after),
    )

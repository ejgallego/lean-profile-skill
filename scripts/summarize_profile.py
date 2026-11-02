#!/usr/bin/env python3
"""Summarize a sampled profile for reading without a browser or a viewer."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import sys

UNKNOWN = re.compile(r"0x[0-9a-fA-F]+\Z|\[unknown\]\Z")
KERNEL = re.compile(r"0xffff[0-9a-fA-F]{12}\Z")
# The profiler and kernel helpers, not the workload. Selecting one by name includes it.
AUXILIARY = re.compile(r"samply\Z|iou-sqp-")
# Frames that end a complete user-space stack.
# A thread at or above this share of the weight gets its own stack-quality check,
# provided it has enough weight for a percentage to mean anything.
MATERIAL_SHARE = 0.1
MINIMUM_THREAD_WEIGHT = 20
THREAD_ENTRY = re.compile(r"(?:^|_)start\Z|_libc_start|start_thread\Z|clone3?\Z")


def read_firefox(raw):
    profile = json.loads(raw)
    if not isinstance(profile, dict) or not isinstance(profile.get("threads"), list):
        raise ValueError("Expected Firefox Profiler JSON or perf script text")
    shared = profile.get("shared", {}).get("stringArray")
    threads = [dict(name=item.get("name", "?"), pid=item.get("pid"), tid=item.get("tid"),
                    weight_type=item["samples"].get("weightType", "samples"),
                    rows=list(firefox_rows(item, shared)))
               for item in profile["threads"] if item["samples"].get("stack")]
    meta = profile.get("meta", {})
    return threads, f'{meta.get("product")}: interval {meta.get("interval")} ms'


def same_length(table, *columns):
    lengths = {len(table[column]) for column in columns}
    if len(lengths) != 1:
        raise ValueError(f"Profile columns {columns} differ in length")


def firefox_rows(thread, shared):
    """Yield (weight, leaf-first frame names) for each distinct sample stack."""
    strings = shared if shared is not None else thread["stringArray"]
    stacks, frames, funcs = thread["stackTable"], thread["frameTable"], thread["funcTable"]
    samples = thread["samples"]
    same_length(stacks, "prefix", "frame")
    weights = samples.get("weight") or [1] * len(samples["stack"])
    if len(weights) != len(samples["stack"]):
        raise ValueError("Sample weights and stacks differ in length")
    totals = Counter()
    for stack, weight in zip(samples["stack"], weights):
        if stack is not None:
            totals[stack] += weight
    for stack, weight in totals.items():
        chain = []
        while stack is not None:
            name = strings[funcs["name"][frames["func"][stacks["frame"][stack]]]]
            chain.append("[kernel]" if KERNEL.match(name) else name)
            stack = stacks["prefix"][stack]
        yield weight, chain


def read_perf_script(text):
    """Parse `perf script -F comm,tid,ip,sym`: a header line, then leaf-first frames."""
    threads, header, chain = {}, None, []

    def flush():
        if header is not None and chain:
            threads.setdefault(header, Counter())[tuple(chain)] += 1

    for line in text.splitlines():
        if not line.strip():
            flush()
            header, chain = None, []
        elif line[0].isspace():
            parts = line.split(None, 1)
            if header is None or len(parts) != 2:
                raise ValueError("Expected `perf script -F comm,tid,ip,sym` output")
            chain.append(re.sub(r"\+0x[0-9a-f]+$", "", parts[1].strip()))
        else:
            flush()
            header, chain = line.strip(), []
    flush()
    if not threads:
        raise ValueError("Expected Firefox Profiler JSON or perf script text")
    rows = []
    for header, stacks in threads.items():
        comm, _, tid = header.rpartition(" ")
        rows.append(dict(name=comm.strip(), pid=None, tid=tid, weight_type="samples",
                         rows=[(weight, list(chain)) for chain, weight in stacks.items()]))
    return rows, "perf script"


def read_profile(path):
    raw = sys.stdin.buffer.read() if str(path) == "-" else Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return read_firefox(raw) if raw.lstrip()[:1] == b"{" else read_perf_script(raw.decode())


def summarize(threads, source="profile", *, top=15, thread=None, tid=None):
    self_time, inclusive, chains, depths = Counter(), Counter(), Counter(), Counter()
    summaries = []
    total = unknown = rooted = 0
    selected = [item for item in threads
                if (thread is None or thread in str(item["name"]))
                and (tid is None or tid == str(item["tid"]))]
    if thread is None and tid is None:
        selected = [item for item in selected if not AUXILIARY.match(str(item["name"]))] or selected
    trace = any(item["weight_type"].startswith("tracing") for item in selected)
    for item in threads:
        weight = thread_rooted = thread_unknown = 0
        chosen = item in selected
        for row_weight, chain in item["rows"]:
            weight += row_weight
            thread_rooted += row_weight if THREAD_ENTRY.search(chain[-1]) else 0
            thread_unknown += row_weight if UNKNOWN.match(chain[0]) else 0
            if chosen:
                self_time[chain[0]] += row_weight
                depths[len(chain)] += row_weight
                for name in set(chain):
                    inclusive[name] += row_weight
                chains[" <- ".join(chain[:5])] += row_weight
        summaries.append(dict(name=item["name"], pid=item["pid"], tid=item["tid"], weight=weight,
                              selected=chosen,
                              rooted_percent=100 * thread_rooted / weight if weight else 0.0,
                              unknown_leaf_percent=100 * thread_unknown / weight if weight else 0.0))
        if chosen:
            total, rooted, unknown = total + weight, rooted + thread_rooted, unknown + thread_unknown
    if not total:
        raise ValueError("No samples matched")
    warnings = []
    if trace:
        warnings.append("Weights are recorded scope milliseconds, not samples: a parent's self share "
                        "is its residual, including work below the trace threshold, not a hotspot.")
    elif total < 100:
        warnings.append(f"Only {total} sample weight units; percentages are coarse.")
    if unknown / total > 0.5:
        warnings.append("Most leaf frames are unsymbolicated addresses. Only `lake samply` output "
                        "is symbolicated in the file; use `perf script` for other captures.")
    if not trace:
        remedy = ("prefer `lake samply` stacks where sampling is permitted, or confirm callers with "
                  "a debugger census." if source == "perf script"
                  else "confirm callers with a debugger census.")
        # Well-rooted helpers must not hide broken stacks on the thread doing the work.
        for row in summaries:
            material = row["weight"] >= max(MATERIAL_SHARE * total, MINIMUM_THREAD_WEIGHT)
            if row["selected"] and material and row["rooted_percent"] < 50:
                warnings.append(f'Thread {row["name"]} (tid {row["tid"]}) carries {row["weight"]} of '
                                f'{total} weight, but only {row["rooted_percent"]:.1f}% of it reaches '
                                "a thread entry, so its caller frames may be missing or skipped even "
                                f"when every name looks valid. Trust self time; {remedy}")

    def table(counter):
        # Name breaks ties: frame sets iterate in per-process hash order.
        ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:top]
        return [dict(percent=100 * value / total, name=name) for name, value in ranked]

    return dict(source=source, total=total, trace=trace,
                unknown_leaf_percent=100 * unknown / total,
                rooted_stack_percent=100 * rooted / total,
                stack_depths=sorted(depths.items()),
                threads=sorted(summaries, key=lambda row: -row["weight"]), warnings=warnings,
                self=table(self_time), inclusive=table(inclusive), stacks=table(chains))


def thread_id(row):
    return f'tid {row["tid"]}' if row["pid"] is None else f'pid {row["pid"]}, tid {row["tid"]}'


def render(summary):
    lines = [f'{summary["source"]}, weight {summary["total"]}: unknown leaf frames '
             f'{summary["unknown_leaf_percent"]:.1f}%, stacks reaching a thread entry '
             f'{summary["rooted_stack_percent"]:.1f}%']
    lines += [f'warning: {warning}' for warning in summary["warnings"]]
    lines.append("threads (confirm the intended workers carry the weight and reach an entry):")
    lines += [f'  {row["weight"]:>8}  rooted {row["rooted_percent"]:5.1f}%  unknown '
              f'{row["unknown_leaf_percent"]:5.1f}%  {row["name"]} ({thread_id(row)})'
              for row in summary["threads"] if row["weight"] and row["selected"]]
    excluded = [row for row in summary["threads"] if row["weight"] and not row["selected"]]
    if excluded:
        names = ", ".join(sorted({str(row["name"]) for row in excluded}))
        lines.append(f'  excluded {sum(row["weight"] for row in excluded)} weight: {names}')
    for key, heading in (("self", "self"), ("inclusive", "inclusive"), ("stacks", "top stacks, leaf first")):
        lines.append(f"{heading}:")
        lines += [f'  {row["percent"]:6.2f}%  {row["name"]}' for row in summary[key]]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path,
                        help="Firefox Profiler JSON, optionally gzipped, or `perf script` text; - for stdin")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--thread", help="Only threads whose name contains this text")
    parser.add_argument("--tid", help="Only the thread with this exact ID")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    threads, source = read_profile(args.profile)
    result = summarize(threads, source, top=args.top, thread=args.thread, tid=args.tid)
    print(json.dumps(result, indent=2) if args.json else render(result))

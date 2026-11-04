#!/usr/bin/env python3
"""Probe which native sampling backends this host permits; fail when none does.

Each installed backend records a trivial Python process. A backend counts as
usable only when that recording succeeds, so the verdict is tested, not
inferred from `perf_event_paranoid`. A failed probe is reported with its own
diagnostic, which may show a permission refusal or another cause. Exit 0 names
the backend to use; exit 3 means native attribution cannot proceed, and the
message says what the machine's owner can look at. Nothing is changed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROBE_TARGET = [sys.executable, "-c", "pass"]
PROBE_SECONDS = 60
BLOCKED = 3
PARANOID = Path("/proc/sys/kernel/perf_event_paranoid")

# Preference order: samply output reads better, perf works at a stricter level.
BACKENDS = {
    "samply": ["record", "--save-only", "-o", os.devnull, "--"],
    "perf": ["record", "-e", "cycles:u", "-F", "997", "--user-callchains",
             "--call-graph", "dwarf", "-o", os.devnull, "--"],
}


def read_paranoid(path: Path = PARANOID) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def run_probe(argv: list[str]) -> tuple[int | None, str]:
    """Return the exit status and the tail of stderr; None means it did not finish."""
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=PROBE_SECONDS)
    except subprocess.TimeoutExpired:
        return None, f"probe did not finish within {PROBE_SECONDS} s"
    except OSError as error:
        return None, str(error)
    lines = result.stderr.decode(errors="replace").strip().splitlines()
    return result.returncode, "\n".join(lines[-5:])


def lake_has_samply(run: Callable[[list[str]], subprocess.CompletedProcess[bytes]]) -> bool | None:
    """Lake's integrated command (Lean 4.36+) uses samply's permission, so it is reported, not probed."""
    if shutil.which("lake") is None or not any(Path(name).exists() for name in ("lakefile.toml", "lakefile.lean")):
        return None
    try:
        result = run(["lake", "--help"])
    except (OSError, subprocess.TimeoutExpired):
        return None
    return any(line.split()[:1] == ["samply"] for line in result.stdout.decode(errors="replace").splitlines())


def assess(paranoid: int | None, which: Callable[[str], str | None],
           probe: Callable[[list[str]], tuple[int | None, str]]) -> dict[str, Any]:
    backends = []
    for name, arguments in BACKENDS.items():
        path = which(name)
        entry: dict[str, Any] = dict(name=name, path=path, usable=False)
        if path is not None:
            argv = [path, *arguments, *PROBE_TARGET]
            status, diagnostic = probe(argv)
            entry.update(command=argv, exit_status=status, usable=status == 0,
                         diagnostic=diagnostic)
        backends.append(entry)
    selected = next((entry["name"] for entry in backends if entry["usable"]), None)
    return dict(system=platform.system(), perf_event_paranoid=paranoid,
                backends=backends, selected=selected)


def blocked_message(report: dict[str, Any]) -> str:
    level = report["perf_event_paranoid"]
    installed = [entry for entry in report["backends"] if entry["path"]]
    lines = ["No sampling backend is usable on this host, so native attribution stops here.",
             "Timings and counters cannot show where the time goes, so no hotspot claim is made."]
    for entry in installed:
        status = entry["exit_status"]
        outcome = f"exit {status}" if status is not None else "did not finish"
        lines.append(f"- {entry['name']} probe failed ({outcome}): "
                     + (entry["diagnostic"].splitlines() or ["no diagnostic"])[-1])
    for entry in report["backends"]:
        if not entry["path"]:
            lines.append(f"- {entry['name']} is not installed")
    options = []
    if installed:
        options.append("resolve the failure each diagnostic above shows; it, not this list, "
                       "names the cause")
    if installed and level is not None and level > 1:
        options.append(f"if a diagnostic is a permission error, lowering kernel.perf_event_paranoid "
                       f"(now {level}) until the next reboot may resolve it:\n"
                       "      sudo sysctl kernel.perf_event_paranoid=1")
    elif installed and level is not None:
        options.append("if a diagnostic is a permission error although the kernel level permits "
                       "sampling, look for a container, a seccomp profile or a missing CAP_PERFMON")
    if not installed:
        options.append("install samply (`cargo install --locked samply`) or Linux perf")
    elif level == 2 and not any(entry["name"] == "perf" for entry in installed):
        options.append("install Linux perf, which can often sample user space at level 2")
    options.append("run the investigation on a host where sampling is permitted")
    lines += ["", "To continue, the machine's owner can:"]
    lines += [f"- {option}" for option in options]
    lines.append("Then rerun this check. Making these changes is the owner's decision.")
    return "\n".join(lines)


def describe(report: dict[str, Any], lake_samply: bool | None) -> str:
    lines = [f"perf_event_paranoid: {report['perf_event_paranoid']}"]
    for entry in report["backends"]:
        state = ("not installed" if not entry["path"]
                 else "usable" if entry["usable"] else "probe failed")
        lines.append(f"{entry['name']}: {state}")
    if lake_samply is not None:
        lines.append(f"lake samply: {'available' if lake_samply else 'not in this toolchain'}")
    selected = report["selected"]
    if selected == "samply":
        lines.append("Use " + ("`lake samply`" if lake_samply else "samply") + " for attribution.")
    elif selected == "perf":
        lines.append("Use user-space `perf record` (`-e cycles:u --user-callchains`) for attribution.")
    else:
        lines.append("")
        lines.append(blocked_message(report))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args()
    report = assess(read_paranoid(), shutil.which, run_probe)
    lake_samply = lake_has_samply(lambda argv: subprocess.run(
        argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=PROBE_SECONDS))
    report["lake_samply"] = lake_samply
    if args.json:
        print(json.dumps(report, indent=2))
        if report["selected"] is None:
            print(blocked_message(report), file=sys.stderr)
    else:
        print(describe(report, lake_samply))
    return 0 if report["selected"] else BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())

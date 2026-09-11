#!/usr/bin/env python3
"""Build a technical review from scoped raw evidence, without running benchmarks.

AI-generated report infrastructure from the SF-in-Lean profiling investigation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from review_data import load
from review_html import render_page

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def build(manifest_path, out, plots=False):
    out = Path(out).absolute()
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite {out}")
    model, manifest_bytes, copies = load(manifest_path)
    # Optional plotting imports fail before creating any report output.
    plotter = None
    if plots:
        try:
            from review_plots import render as plotter
        except ImportError as error:
            raise ValueError(
                "--plots requires Matplotlib; install it explicitly or omit --plots"
            ) from error
    template = (ASSETS / "review.html").read_text(encoding="utf-8")
    static_files = {
        name: (ASSETS / name).read_bytes() for name in ("review.js", "review.css")
    }

    page = render_page(model, out, template, plots)
    # All manifest/data/artifact/template validation precedes output creation.
    out.mkdir(parents=True)
    if plotter:
        model["figures"] = plotter(model, out / "figures")
    for name, snapshot in copies:
        (out / name).write_bytes(snapshot)
    for name, snapshot in static_files.items():
        (out / name).write_bytes(snapshot)
    (out / "source-manifest.json").write_bytes(manifest_bytes)
    (out / "review-data.json").write_text(
        json.dumps(model, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    return out / "index.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--out", type=Path, required=True, help="Fresh output directory"
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Generate SVG/PNG distributions (requires Matplotlib)",
    )
    args = parser.parse_args()
    print(build(args.manifest, args.out, plots=args.plots))

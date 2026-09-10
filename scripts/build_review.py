#!/usr/bin/env python3
"""Build a technical review from scoped raw evidence, without running benchmarks.

AI-generated report infrastructure from the SF-in-Lean profiling investigation.
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

from review_data import load, stats, summarize  # shared validated statistics API

ASSETS = Path(__file__).resolve().parent.parent / "assets"
E = html.escape


def paragraphs(value):
    return "".join(f"<p>{E(p)}</p>" for p in value.split("\n\n"))


def table(headers, rows):
    return (
        '<div class="scroll"><table><thead><tr>'
        + "".join(f'<th scope="col">{header}</th>' for header in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        + "</tbody></table></div>"
    )


def distribution(s):
    return [
        str(s["n"]),
        f'{s["median"]:.3f}',
        f'{s["iqr"]:.3f}',
        f'{s["min"]:.3f}–{s["max"]:.3f}',
    ]


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

    def href(path):
        return quote(os.path.relpath(path, out), safe="/")

    def artifact_link(path, label):
        return f'<a href="{E(href(path), quote=True)}">{E(label)}</a>'

    def figure(path, title, caption):
        return (
            f'<figure><a href="{E(path, quote=True)}"><img loading="lazy" src="{E(path, quote=True)}" alt="{E(title, quote=True)}"></a>'
            f"<figcaption>{E(caption)}</figcaption></figure>"
        )

    def profile(item):
        source = item["artifact_path"]
        url = E(href(source), quote=True)
        content = artifact_link(source, "Open / download artifact")
        if item["kind"] == "perfetto":
            content += f' · <button data-perfetto="{url}" data-title="{E(item["title"], quote=True)}">Open in Perfetto</button>'
        elif item["kind"] == "image":
            content += figure(href(source), item["title"], item["note"])
        elif item["kind"] == "viewer":
            frame_id = f'frame-{item["id"]}'
            content += (
                f' · <button data-viewer="{frame_id}" aria-controls="{frame_id}" aria-expanded="false">Show interactive profile</button>'
                f'<iframe id="{frame_id}" title="{E(item["title"], quote=True)}" data-source="{url}" hidden></iframe>'
            )
        return (
            f'<article class="profile" id="{item["id"]}"><h3>{E(item["title"])}</h3>'
            f'<p class="identity">{E(item["boundary"])} · {E(item["identity"])}</p>'
            + (paragraphs(item["note"]) if item["kind"] != "image" else "")
            + f'<div class="profile-links">{content}</div></article>'
        )

    def metadata(item):
        return (
            f'<p><code>{E(item["command"])}</code> · {E(item["cohort"])}</p>'
            f'<p class="identity">{E(item["boundary"])} · {E(item["identity"])}</p>'
        )

    def resource_note(series_data):
        labels = {
            "user_s": "user CPU (s)",
            "system_s": "system CPU (s)",
            "peak_rss_kib": "peak RSS (KiB)",
        }
        present = [
            f'{labels[k]}: {s["median"]:.3f}'
            for k, s in series_data["statistics"].items()
            if k in labels
        ]
        return (
            '<p class="resource">Separate resource medians — '
            + E("; ".join(present))
            + ".</p>"
            if present
            else ""
        )

    baseline_html = []
    for item in model["baselines"]:
        s = item["series"]["statistics"]["wall_s"]
        baseline_html.append(
            f'<article id="{item["id"]}"><h3>{E(item["title"])}</h3>'
            + metadata(item)
            + table(
                ["Configuration", "n", "Median, s", "IQR, s", "Range, s"],
                [[E(item["configuration"])] + distribution(s)],
            )
            + resource_note(item["series"])
            + paragraphs(item["note"])
            + f'<p class="references"><a href="{item["copied_samples"]}">Raw baseline observations</a>; {len(item["excluded"])} warmup/excluded rows retained.</p></article>'
        )
    progress_html = []
    if "progress" in model:
        progress = model["progress"]
        by_id = {c["id"]: c for c in model["comparisons"]}
        progress_html.append(paragraphs(progress["note"]))
        for key, title in [
            ("selected", "Selected experiments"),
            ("totals", "Directly measured cumulative comparisons"),
        ]:
            rows = []
            for cid in progress[key]:
                c = by_id[cid]
                s = c["statistics"]
                a = s["control"]["median"]
                b = s["candidate"]["median"]
                saving = s["paired_saving_s"]
                rows.append(
                    [
                        f'<a href="#{cid}">{E(c["title"])}</a><small>{E(c["command"])} · {E(c["cohort"])}</small>',
                        f"{a:.3f} → {b:.3f}",
                        f'{s["median_reduction_pct"]:+.1f}%',
                        f'{saving["median"]:+.3f}',
                        f'{s["candidate_faster"]}/{saving["n"]}',
                    ]
                )
            if rows:
                progress_html.append(
                    f"<h3>{title}</h3>"
                    + table(
                        [
                            "Comparison / workload",
                            "Control → candidate<br>median wall, s",
                            "Median reduction",
                            "Paired saving<br>median, s",
                            "Faster pairs",
                        ],
                        rows,
                    )
                )
        if progress["selected"] or progress["totals"]:
            progress_html.append(
                "<p>Percentages compare group medians; paired savings use the original matched observations. Totals reference directly measured comparisons. The builder does not sum incremental savings or multiply ratios across experiments.</p>"
            )
        if progress["historical"]:
            rows = []
            for h in progress["historical"]:
                a, b = h["before"], h["after"]
                rows.append(
                    [
                        E(h["title"]) + f'<small>{E(h["note"])}</small>',
                        f'{a["statistics"]["median"]:.3f} → {b["statistics"]["median"]:.3f}',
                        f'{h["median_reduction_pct"]:+.1f}%',
                        E(a["configuration"])
                        + " → "
                        + E(b["configuration"])
                        + f'<small>{E(a["identity"])} → {E(b["identity"])}<br>{E(a["cohort"])} → {E(b["cohort"])}</small>',
                    ]
                )
            progress_html.append(
                "<h3>Historical endpoints — unpaired</h3><p>Descriptive comparisons of separate distributions. These are not matched speedups or confidence intervals; host, cache or campaign conditions may differ.</p>"
                + table(
                    [
                        "Observation",
                        "Earlier → later<br>median wall, s",
                        "Historical median reduction",
                        "Source configurations and identities",
                    ],
                    rows,
                )
            )
    comparison_html = []
    for item in model["comparisons"]:
        s = item["statistics"]
        saving = s["paired_saving_s"]
        rows = [
            [E(item[key])] + distribution(s[key]) for key in ("control", "candidate")
        ]
        content = (
            f'<article class="comparison" id="{item["id"]}"><h3>{E(item["title"])}</h3>'
            + metadata(item)
            + table(["Configuration", "n", "Median, s", "IQR, s", "Range, s"], rows)
            + f'<p>Paired saving (control − candidate): median <strong>{saving["median"]:+.3f}s</strong>, IQR {saving["iqr"]:.3f}s, range {saving["min"]:+.3f} to {saving["max"]:+.3f}s; candidate faster in {s["candidate_faster"]}/{saving["n"]} pairs.</p>'
        )
        for key in ("control", "candidate"):
            resources = resource_note(s["series"][key])
            if resources:
                content += f'<p class="identity">{E(item[key])}</p>' + resources
        content += f'<p><strong>{E(item["decision"])}</strong></p>' + paragraphs(
            item["note"]
        )
        if plots:
            content += figure(
                f'figures/{item["id"]}.svg',
                item["title"],
                "All included observations; bars span the 25th–75th percentiles, black ticks mark medians, and thin lines span full ranges. Positive paired saving means faster. Descriptive spreads, not confidence intervals.",
            )
        content += f'<p class="references">{len(s["excluded"])} warmup/excluded rows retained. <a href="{item["copied_samples"]}">Raw samples</a></p>'
        content += "".join(
            profile(p) for p in model["profiles"] if p.get("comparison") == item["id"]
        )
        comparison_html.append(content + "</article>")
    attribution_html = "".join(
        f'<h3>{E(a["title"])}</h3>' + paragraphs(a["text"])
        for a in model["attribution"]
    )
    attribution_html += "".join(
        profile(p) for p in model["profiles"] if "comparison" not in p
    )
    sections = []
    navigation = []

    def section(sid, title, body):
        if body:
            sections.append(f'<section id="{sid}"><h2>{title}</h2>{body}</section>')
            navigation.append(f'<a href="#{sid}">{title}</a>')

    if plots and model["baselines"]:
        baseline_html.append(
            figure(
                "figures/baselines.svg",
                "Baseline observations",
                "All included baseline wall times. Thick intervals show IQR; black ticks show medians; thin intervals show full ranges. These are distinct labeled workloads, not matched pairs.",
            )
        )
    section("baselines", "Baseline", "".join(baseline_html))
    section("progress", "Summary of improvements", "".join(progress_html))
    section("attribution", "Phase attribution and profiles", attribution_html)
    methods = (
        "<p>Compare each candidate with its own control, workload and timing boundary. IQR uses inclusive linear interpolation. A median of paired differences can differ from the difference of group medians. Decisions are supplied by the investigator; they are not inferred from positive savings.</p>"
        '<label for="filter">Find an experiment</label> <input id="filter" type="search"><span id="count" aria-live="polite"></span>'
    )
    section(
        "measurements",
        "Experiments",
        methods + "".join(comparison_html) if comparison_html else "",
    )
    links = " · ".join(
        artifact_link(item["artifact_path"], item["title"]) for item in model["links"]
    )
    evidence = (
        (f"<p>{links}</p>" if links else "")
        + '<p><a href="review-data.json">Statistics and provenance</a> · <a href="source-manifest.json">Original input manifest</a></p>'
    )
    evidence += "<p>CSV snapshots are copied into this report. Profile files remain linked at their original locations; serve their common ancestor over HTTP. Perfetto opens its online UI and receives the selected trace locally in the browser. This builder runs no benchmarks and does not validate a trace’s internal structure.</p>"
    section("evidence", "Evidence and reproduction", evidence)
    replacements = dict(
        TITLE=E(model["title"]),
        SUMMARY=paragraphs(model["summary"]),
        NAVIGATION=" · ".join(navigation),
        SECTIONS="".join(sections),
    )
    page = re.sub(
        r"\{\{(TITLE|SUMMARY|NAVIGATION|SECTIONS)\}\}",
        lambda match: replacements[match[1]],
        template,
    )
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

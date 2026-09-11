"""Pure HTML rendering over the validated review model; no artifact reads."""

import html
import os
import re
from collections import Counter
from urllib.parse import quote

from review_format import duration, number, time_unit

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


def distribution(s, scale=1):
    if s is None:
        return ["0", "—", "—", "—"]
    return [
        str(s["n"]),
        number(s["median"], scale),
        number(s["iqr"], scale),
        f'{number(s["min"], scale)}–{number(s["max"], scale)}',
    ]


def outcome_summary(values):
    if not values["outcomes"]:
        return "No observations recorded."
    parts = []
    for phase in ("measured", "warmup"):
        rows = [r for r in values["outcomes"] if r["phase"] == phase]
        if not rows:
            continue
        counts = Counter(r["outcome"] for r in rows)
        detail = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
        limits = sorted({r["timeout_s"] for r in rows if r["outcome"] == "timeout"})
        if limits:
            detail += "; timeout limits " + ", ".join(duration(v) for v in limits)
        parts.append(f"{phase}: {detail}")
    return ". ".join(parts) + "."


def outcome_details(values):
    rows = [[E(r["block"]), E(r["phase"]), E(r["outcome"]),
             duration(r["wall_s"]), duration(r.get("timeout_s")),
             "included" if r["included"] else E(r["exclude_reason"] or "warmup")]
            for r in values["outcomes"]]
    note = E(outcome_summary(values))
    if values["censored"]:
        note += " Completed-only distributions are conditional; no full-cohort median is estimated."
    return (f'<p class="outcomes">{note}</p>'
            + ("<details><summary>Recorded outcomes and inclusion</summary>"
               + table(["Block", "Phase", "Outcome", "Observed elapsed", "Timeout limit", "Inclusion"], rows)
               + "</details>" if rows else ""))


def href(path, out):
    return quote(os.path.relpath(path, out), safe="/")


def artifact_link(path, label, out):
    return f'<a href="{E(href(path, out), quote=True)}">{E(label)}</a>'


def figure(path, title, caption):
    return (
        f'<figure><a href="{E(path, quote=True)}"><img loading="lazy" src="{E(path, quote=True)}" alt="{E(title, quote=True)}"></a>'
        f"<figcaption>{E(caption)}</figcaption></figure>"
    )


def profile(item, out):
    source = item["artifact_path"]
    url = E(href(source, out), quote=True)
    content = artifact_link(source, "Open / download artifact", out)
    if item["kind"] == "perfetto":
        content += f' · <button data-perfetto="{url}" data-title="{E(item["title"], quote=True)}">Open in Perfetto</button>'
    elif item["kind"] == "image":
        content += figure(href(source, out), item["title"], item["note"])
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
        f'<p class="identity">{E(item["cohort"])} · {E(item["boundary"])} · {E(item["identity"])}</p>'
        f'<details class="command"><summary>Exact command</summary><pre><code>{E(item["command"])}</code></pre></details>'
    )


def resource_note(series_data):
    labels = {
        "user_s": "user CPU (s)",
        "system_s": "system CPU (s)",
        "peak_rss_kib": "peak RSS (KiB)",
    }
    present = [
        f'{labels[k]}: {number(s["median"])}'
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


def distribution_table(configurations, summaries, outcome_notes=None):
    """Use one unit and the same columns for every distribution table."""
    scale, unit = time_unit([s["max"] for s in summaries if s])
    headers = ["Configuration", "Included n", f"Median, {unit}", f"IQR, {unit}", f"Range, {unit}"]
    rows = [[E(name)] + distribution(summary, scale)
            for name, summary in zip(configurations, summaries)]
    if outcome_notes is not None:
        headers.append("Recorded outcomes")
        for row, note in zip(rows, outcome_notes):
            row.append(E(note))
    return table(headers, rows)


def render_baselines(items, plots):
    baseline_html = []
    for item in items:
        baseline_html.append(
            f'<article id="{item["id"]}"><h3>{E(item["title"])}</h3>'
            + metadata(item)
            + distribution_table([item["configuration"]], [item["series"]["statistics"].get("wall_s")])
            + outcome_details(item["series"])
            + resource_note(item["series"])
            + paragraphs(item["note"])
            + f'<p class="references"><a href="{item["copied_samples"]}">Shared raw dataset</a>; {len(item["excluded"])} warmup/excluded rows retained.</p></article>'
        )
    if plots and items:
        baseline_html.append(
            figure(
                "figures/baselines.svg",
                "Baseline observations",
                "All included baseline wall times. Thick intervals show IQR; black ticks show medians; thin intervals show full ranges. These are distinct labeled workloads, not matched pairs.",
            )
        )
    return "".join(baseline_html)


def render_datasets(items):
    dataset_html = []
    for item in items:
        if len(item["configurations"]) < 3:
            continue
        summaries = [item["series"][c]["statistics"].get("wall_s") for c in item["configurations"]]
        dataset_html.append(
            f'<article id="{item["id"]}"><h3>{E(item["title"])}</h3>' + metadata(item)
            + distribution_table(item["configurations"], summaries,
                                 [outcome_summary(item["series"][c]) for c in item["configurations"]])
            + '<p>Distributions use included completed observations only. Measured timeouts make them conditional on completion; they do not estimate the full cohort. Pairing and availability are checked separately for each requested contrast.</p>'
            + f'<p><a href="{item["copied_samples"]}">Shared raw dataset</a></p></article>'
        )
    return "".join(dataset_html)


def render_progress(progress, comparisons):
    if progress is None:
        return ""
    progress_html = [paragraphs(progress["note"])]
    by_id = {c["id"]: c for c in comparisons}
    for key, title in [
        ("selected", "Selected experiments"),
        ("totals", "Directly measured cumulative comparisons"),
    ]:
        rows = []
        for cid in progress[key]:
            c = by_id[cid]
            s = c["statistics"]
            a = s["control"]["median"] if s["control"] else None
            b = s["candidate"]["median"] if s["candidate"] else None
            saving = s["paired_saving_s"]
            rows.append(
                [
                    f'<a href="#{cid}">{E(c["title"])}</a><small>{E(c["cohort"])}</small>',
                    f"{duration(a)} → {duration(b)}",
                    f'{s["median_reduction_pct"]:+.3g}%' if saving else "Not estimated",
                    duration(saving["median"]) if saving else E(s["unavailable_reason"]),
                    f'{s["candidate_faster"]}/{saving["n"]}' if saving else "—",
                ]
            )
        if rows:
            progress_html.append(
                f"<h3>{title}</h3>"
                + table(
                    [
                        "Comparison / workload",
                        "Control → candidate<br>included-completion median",
                        "Median reduction",
                        "Paired saving<br>median / availability",
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
                    f'{duration(a["statistics"]["median"] if a["statistics"] else None)} → {duration(b["statistics"]["median"] if b["statistics"] else None)}',
                    f'{h["median_reduction_pct"]:+.3g}%' if h["median_reduction_pct"] is not None else "Not estimated: missing completions or measured censoring",
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
                    "Earlier → later<br>included-completion median",
                    "Historical median reduction",
                    "Source configurations and identities",
                ],
                rows,
            )
        )
    return "".join(progress_html)


def render_comparison(item, profiles, out, plots):
    s = item["statistics"]
    saving = s["paired_saving_s"]
    content = (
        f'<article class="comparison" data-decision="{item["decision_status"] or "unclassified"}" id="{item["id"]}"><h3>{E(item["title"])}</h3>'
        + metadata(item)
        + distribution_table([item["control"], item["candidate"]], [s["control"], s["candidate"]])
    )
    if saving:
        delta_scale, delta_unit = time_unit([saving["min"], saving["max"]])
        content += f'<p>Paired saving (control − candidate), {delta_unit}: median <strong>{number(saving["median"], delta_scale, True)}</strong>, IQR {number(saving["iqr"], delta_scale)}, range {number(saving["min"], delta_scale, True)} to {number(saving["max"], delta_scale, True)}; candidate faster in {s["candidate_faster"]}/{saving["n"]} pairs.</p>'
    else:
        content += f'<p class="outcomes">{E(s["unavailable_reason"])}</p>'
    for key in ("control", "candidate"):
        content += f'<h4>{E(item[key])}: recorded outcomes</h4>' + outcome_details(s["series"][key])
        resources = resource_note(s["series"][key])
        if resources:
            content += f'<p class="identity">{E(item[key])}</p>' + resources
    if item["decision_status"]:
        content += f'<p>Investigator decision: <strong>{E(item["decision_status"])}</strong>.</p>'
    content += paragraphs(item["decision"]) + paragraphs(
        item["note"]
    )
    if plots:
        content += figure(
            f'figures/{item["id"]}.svg',
            item["title"],
            "Included completed observations only; bars span the 25th–75th percentiles, black ticks mark medians, and thin lines span full ranges. Paired estimates are withheld for measured censoring or incomplete included blocks. Descriptive spreads, not confidence intervals.",
        )
    content += f'<p class="references">{len(s["excluded"])} warmup/excluded rows retained. <a href="{item["copied_samples"]}">Shared raw dataset</a></p>'
    content += "".join(
        profile(p, out) for p in profiles if p.get("comparison") == item["id"]
    )
    return content + "</article>"


def render_page(model, out, template, plots=False):
    comparison_html = [render_comparison(item, model["profiles"], out, plots)
                       for item in model["comparisons"]]
    attribution_html = "".join(
        f'<h3>{E(a["title"])}</h3>' + paragraphs(a["text"])
        for a in model["attribution"]
    )
    attribution_html += "".join(
        profile(p, out) for p in model["profiles"] if "comparison" not in p
    )
    sections = []
    navigation = []

    def section(sid, title, body):
        if body:
            sections.append(f'<section id="{sid}"><h2>{title}</h2>{body}</section>')
            navigation.append(f'<a href="#{sid}">{title}</a>')

    section("baselines", "Baseline", render_baselines(model["baselines"], plots))
    section("datasets", "Multi-configuration overview", render_datasets(model["datasets"]))
    section("progress", "Summary of improvements", render_progress(model.get("progress"), model["comparisons"]))
    section("attribution", "Phase attribution and profiles", attribution_html)
    methods = (
        "<p>Compare each candidate with its own control, workload and timing boundary. IQR uses inclusive linear interpolation. A median of paired differences can differ from the difference of group medians. Decisions are supplied by the investigator; they are not inferred from positive savings.</p>"
        '<label for="filter">Find an experiment</label> <input id="filter" type="search"> '
        '<label for="decision-filter">Decision</label> <select id="decision-filter">'
        '<option value="all">All decisions</option><option value="accepted">Accepted</option>'
        '<option value="rejected">Rejected</option><option value="inconclusive">Inconclusive</option>'
        '<option value="unclassified">Unclassified</option></select><span id="count" aria-live="polite"></span>'
    )
    section(
        "measurements",
        "Experiments",
        methods + "".join(comparison_html) if comparison_html else "",
    )
    links = " · ".join(
        artifact_link(item["artifact_path"], item["title"], out) for item in model["links"]
    )
    evidence = (
        (f"<p>{links}</p>" if links else "")
        + '<p><a href="review-data.json">Statistics and provenance</a> · <a href="source-manifest.json">Original input manifest</a></p>'
    )
    evidence += "<p>Each CSV or JSONL dataset is snapshotted once for all its contrasts. Profile files remain linked at their original locations; serve their common ancestor over HTTP. Perfetto opens its online UI and receives the selected trace locally in the browser. This builder runs no benchmarks and does not validate a trace’s internal structure.</p>"
    section("evidence", "Evidence and reproduction", evidence)
    replacements = dict(
        TITLE=E(model["title"]),
        SUMMARY=paragraphs(model["summary"]),
        NAVIGATION=" · ".join(navigation),
        SECTIONS="".join(sections),
    )
    return re.sub(
        r"\{\{(TITLE|SUMMARY|NAVIGATION|SECTIONS)\}\}",
        lambda match: replacements[match[1]],
        template,
    )

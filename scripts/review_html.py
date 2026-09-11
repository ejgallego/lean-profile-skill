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


def table(headers, rows, row_attributes=None):
    def attributes(index):
        return ''.join(f' {key}="{E(str(value), quote=True)}"' for key, value in
                       (row_attributes[index] if row_attributes else {}).items())
    return (
        '<div class="scroll"><table><thead><tr>'
        + "".join(f'<th scope="col">{header}</th>' for header in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr" + attributes(index) + ">" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for index, row in enumerate(rows)
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
        f'<p class="identity">{E(item["cohort"])} · {E(item["boundary"])}</p><p class="identity">{E(item["identity"])}</p>'
        f'<details class="command"><summary>Exact command</summary><pre><code>{E(item["command"])}</code></pre></details>'
    )


def evidence_details(item, body, label="Commands, resources and recorded outcomes"):
    return ('<details class="measurement-details"><summary>' + E(label) + '</summary>'
            + metadata(item) + body
            + f'<p class="references"><a href="{item["copied_samples"]}">Shared raw dataset</a></p></details>')


def availability(values):
    """Keep missing/censored results and exclusions visible outside disclosures."""
    measured_excluded = sum(r["phase"] == "measured" for r in values["excluded"])
    if values["censored"]:
        return 'Completed-only distribution; measured timeouts prevent a full-cohort estimate.'
    if not values["statistics"]:
        return 'No included measurements. ' + outcome_summary(values)
    return f'{measured_excluded} measured outcomes excluded; see recorded outcomes.' if measured_excluded else ''


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
    if not items:
        return ""
    summaries = [item["series"]["statistics"].get("wall_s") for item in items]
    scale, unit = time_unit([s["max"] for s in summaries if s])
    rows = []
    details = []
    for item in items:
        values = item["series"]
        warning = availability(values)
        label = (f'<span id="{item["id"]}">{E(item["title"])}</span>'
                 + f'<small>{E(item["configuration"])} · {E(item["boundary"])}</small>')
        if warning:
            label += f'<small class="availability">{E(warning)}</small>'
        rows.append([label] + distribution(values["statistics"].get("wall_s"), scale))
        details.append(evidence_details(item, paragraphs(item["note"]) + outcome_details(values)
                                       + resource_note(values), item["title"] + ' — method and evidence'))
    baseline_html = [table(["Workload", "Included n", f"Median, {unit}", f"IQR, {unit}", f"Range, {unit}"], rows)]
    if plots:
        baseline_html.append(
            figure(
                "figures/baselines.svg",
                "Baseline observations",
                "All included baseline wall times. Thick intervals show IQR; black ticks show medians; thin intervals show full ranges. These are distinct labeled workloads, not matched pairs.",
            )
        )
    baseline_html.extend(details)
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
                    f'<a href="#{cid}">{E(comparison_title(c))}</a>',
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
                    "Median wall time<br>control → candidate",
                        "Median reduction",
                    "Median paired saving",
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
                    + f'<details><summary>Capture identities</summary><small>{E(a["identity"])} → {E(b["identity"])}<br>{E(a["cohort"])} → {E(b["cohort"])}</small></details>',
                ]
            )
        progress_html.append(
            "<h3>Historical endpoints — unpaired</h3><p>Descriptive comparisons of separate distributions. These are not matched speedups or confidence intervals; host, cache or campaign conditions may differ.</p>"
            + table(
                [
                    "Observation",
                    "Median wall time<br>earlier → later",
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
        + paragraphs(item["note"])
        + f'<p class="identity">{E(item["boundary"])}</p>'
        + distribution_table([item["control"], item["candidate"]], [s["control"], s["candidate"]])
    )
    if saving:
        delta_scale, delta_unit = time_unit([saving["min"], saving["max"]])
        content += f'<p>Paired saving (control − candidate), {delta_unit}: median <strong>{number(saving["median"], delta_scale, True)}</strong>, IQR {number(saving["iqr"], delta_scale)}, range {number(saving["min"], delta_scale, True)} to {number(saving["max"], delta_scale, True)}; candidate faster in {s["candidate_faster"]}/{saving["n"]} pairs.</p>'
    else:
        content += f'<p class="outcomes">{E(s["unavailable_reason"])}</p>'
    for side in ("control", "candidate"):
        warning = availability(s["series"][side])
        if warning:
            content += f'<p class="availability">{E(item[side])}: {E(warning)}</p>'
    content += paragraphs(item["decision"])
    if plots:
        content += figure(
            f'figures/{item["id"]}.svg',
            item["title"],
            "Included completed observations only; bars span the 25th–75th percentiles, black ticks mark medians, and thin lines span full ranges. Paired estimates are withheld for measured censoring or incomplete included blocks. Descriptive spreads, not confidence intervals.",
        )
    detail = ''
    if item["decision_status"]:
        detail += f'<p>Investigator decision: <strong>{E(item["decision_status"])}</strong>.</p>'
    for key in ("control", "candidate"):
        detail += f'<h4>{E(item[key])}: recorded outcomes</h4>' + outcome_details(s["series"][key]) + resource_note(s["series"][key])
    content += evidence_details(item, detail)
    content += "".join(
        profile(p, out) for p in profiles if p.get("comparison") == item["id"]
    )
    return content + "</article>"


def comparison_title(item):
    return item['group'] + ' — ' + item['title'] if 'group' in item else item['title']


def compact_distribution(stats):
    if stats is None:
        return 'Not estimated'
    scale, unit = time_unit([stats['min'], stats['max']])
    return (f'<strong>{number(stats["median"], scale)} {unit}</strong> [{number(stats["iqr"], scale)}]'
            + f'<small>{number(stats["min"], scale)}–{number(stats["max"], scale)} {unit}; n={stats["n"]}</small>')


def render_group(items, profiles, out, plots):
    """Presentation only: each row keeps its own validated dataset and contrast."""
    first = items[0]
    rows, attrs, evidence = [], [], []
    context = ' '.join(first[key] for key in ('group', 'note', 'decision'))
    for index, item in enumerate(items):
        s = item['statistics']
        saving = s['paired_saving_s']
        label = E(item['title']) + f'<small>{E(item["boundary"])}</small>'
        for side in ('control', 'candidate'):
            warning = availability(s['series'][side])
            if warning:
                label += f'<small class="availability">{E(item[side])}: {E(warning)}</small>'
        rows.append([
            label,
            compact_distribution(s['control']) + f'<small>{E(item["control"])}</small>',
            compact_distribution(s['candidate']) + f'<small>{E(item["candidate"])}</small>',
            f'{s["median_reduction_pct"]:+.3g}%' if saving else 'Not estimated',
            compact_distribution(saving) if saving else E(s['unavailable_reason']),
            f'{s["candidate_faster"]}/{saving["n"]}' if saving else '—',
        ])
        attrs.append({'id':item['id'], 'class':'comparison comparison-row',
                      'data-decision':item['decision_status'] or 'unclassified',
                      'data-context':context + ' ' + item['cohort'] + ' ' + item['identity']})
        detail = ''
        for side in ('control', 'candidate'):
            detail += f'<h4>{E(item[side])}: recorded outcomes</h4>' + outcome_details(s['series'][side]) + resource_note(s['series'][side])
        if item['decision_status']:
            detail += f'<p>Investigator decision: {E(item["decision_status"])}</p>'
        if plots and index > 0:
            detail += figure(f'figures/{item["id"]}.svg', comparison_title(item),
                             'Included observations, median, IQR and range; paired savings on a separate axis.')
        evidence.append(f'<div class="comparison-evidence" data-for="{item["id"]}">'
                        + evidence_details(item, detail, item['title'] + ' — distributions and evidence') + '</div>')
        evidence.extend(f'<div class="comparison-evidence" data-for="{item["id"]}">' + profile(p,out) + '</div>'
                        for p in profiles if p.get('comparison') == item['id'])
    content = ('<article class="comparison-group"><h3>' + E(first['group']) + '</h3>' + paragraphs(first['note'])
               + table(['Workload', 'Control: median [IQR]', 'Candidate: median [IQR]',
                        'Median reduction', 'Paired saving: median [IQR]', 'Faster pairs'], rows, attrs)
               + paragraphs(first['decision']))
    if plots:
        content += (f'<div class="comparison-evidence" data-for="{first["id"]}">'
                    + figure(f'figures/{first["id"]}.svg', comparison_title(first),
                             first['title'] + '. All included observations; median, IQR and full range. Other workload plots are in the evidence below.') + '</div>')
    return content + ''.join(evidence) + '</article>'


def render_comparisons(items, profiles, out, plots):
    rendered, done = [], set()
    for item in items:
        group = item.get('group')
        if group is None:
            rendered.append(render_comparison(item, profiles, out, plots))
        elif group not in done:
            done.add(group)
            rendered.append(render_group([c for c in items if c.get('group') == group], profiles, out, plots))
    return ''.join(rendered)


def comparison_index(items):
    links, seen = [], set()
    for item in items:
        key = ('group', item['group']) if 'group' in item else ('comparison', item['id'])
        if key not in seen:
            seen.add(key)
            links.append(f'<li><a href="#{item["id"]}">{E(item.get("group", item["title"]))}</a></li>')
    if len(links) < 4:
        return ''
    return '<nav class="experiment-index" aria-label="Experiment index"><ol>' + ''.join(links) + '</ol></nav>'


def render_page(model, out, template, plots=False):
    comparison_html = render_comparisons(model["comparisons"], model["profiles"], out, plots)
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
    section("progress", "Summary of improvements", render_progress(model.get("progress"), model["comparisons"]))
    section("attribution", "Phase attribution and profiles", attribution_html)
    methods = (
        "<p>Each workload is compared with its own control. Tables show median [IQR], full range and included n. Paired saving is control minus candidate within recorded rounds; positive is faster. These descriptive spreads are not confidence intervals. Decisions are supplied by the investigator.</p>"
        '<label for="filter">Find an experiment</label> <input id="filter" type="search"> '
        '<label for="decision-filter">Decision</label> <select id="decision-filter">'
        '<option value="all">All decisions</option><option value="accepted">Accepted</option>'
        '<option value="rejected">Rejected</option><option value="inconclusive">Inconclusive</option>'
        '<option value="unclassified">Unclassified</option></select><span id="count" aria-live="polite"></span>'
    )
    section(
        "measurements",
        "Experiments",
        methods + comparison_index(model["comparisons"]) + comparison_html if comparison_html else "",
    )
    links = "".join(
        '<li>' + artifact_link(item["artifact_path"], item["title"], out) + '</li>' for item in model["links"]
    )
    evidence = (
        (f'<details><summary>Source files, validation and reproduction links ({len(model["links"])})</summary><ul>{links}</ul></details>' if links else "")
        + '<p><a href="review-data.json">Statistics and provenance</a> · <a href="source-manifest.json">Original input manifest</a></p>'
    )
    evidence += "<p>Each CSV or JSONL dataset is snapshotted once for all its contrasts. Profile files remain linked at their original locations; serve their common ancestor over HTTP. Perfetto opens its online UI and receives the selected trace locally in the browser. This builder runs no benchmarks and does not validate a trace’s internal structure.</p>"
    datasets = render_datasets(model["datasets"])
    if datasets:
        evidence += '<details id="datasets"><summary>Multi-configuration overview</summary>' + datasets + '</details>'
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

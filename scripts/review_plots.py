"""Optional scientific SVG/PNG figures over the report's validated observations.

AI-generated; imported only when the caller explicitly requests --plots.
"""

from pathlib import Path
import hashlib
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from review_observations import stats
from review_format import time_unit


def interval(ax, values, y, color, scale=1):
    ax.xaxis.set_major_locator(MaxNLocator(nbins=4, min_n_ticks=2))
    if not values:
        ax.text(.02, y, "No included completion", transform=ax.get_yaxis_transform(),
                va="center", fontsize=9)
        return
    values = [v * scale for v in values]
    s = stats(values)
    ax.hlines(y, s["min"], s["max"], color=color, linewidth=1)
    ax.hlines(y, s["q1"], s["q3"], color=color, linewidth=6, alpha=0.4)
    # Deterministic small offsets expose coincident observations without random jitter.
    offsets = [
        y + 0.12 * (i / (len(values) - 1) - 0.5) if len(values) > 1 else y
        for i in range(len(values))
    ]
    ax.scatter(values, offsets, s=18, color=color, alpha=0.8, zorder=3)
    ax.plot(
        s["median"],
        y,
        marker="|",
        markersize=14,
        color="black",
        markeredgewidth=1.5,
        zorder=4,
    )
    ax.grid(axis="x", color="#ddd", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def render(model, output):
    output = Path(output)
    output.mkdir()
    artifacts = []

    def save(fig, name, source_ids):
        fig.tight_layout()
        for suffix in ("svg", "png"):
            path = output / f"{name}.{suffix}"
            fig.savefig(path, dpi=140, bbox_inches="tight")
            artifacts.append(
                dict(
                    path=f"figures/{path.name}",
                    source_ids=source_ids,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    kind="descriptive_observations_not_confidence_intervals",
                )
            )
        plt.close(fig)

    with plt.rc_context(
        {
            "font.size": 10,
            "svg.fonttype": "none",
            "axes.facecolor": "white",
            "figure.facecolor": "white",
        }
    ):
        if model["baselines"]:
            scale, unit = time_unit([r["wall_s"] for b in model["baselines"]
                                     for r in b["series"]["observations"]])
            fig, ax = plt.subplots(
                figsize=(10, max(2.2, 0.6 * len(model["baselines"]) + 1.1))
            )
            for y, b in enumerate(model["baselines"]):
                interval(
                    ax, [r["wall_s"] for r in b["series"]["observations"]], y, "#356a9a", scale
                )
            ax.set_yticks(
                range(len(model["baselines"])), [b["title"] for b in model["baselines"]]
            )
            ax.set_ylim(len(model["baselines"]) - 0.5, -0.5)
            ax.set_xlabel(f"Included completed wall time at each declared boundary ({unit})")
            ax.set_xlim(left=0)
            save(fig, "baselines", [b["id"] for b in model["baselines"]])
        for c in model["comparisons"]:
            result = c["statistics"]
            fig, (left, right) = plt.subplots(
                1, 2, figsize=(10, 2.7), gridspec_kw={"width_ratios": [1.25, 1]}
            )
            scale, unit = time_unit([r["wall_s"] for side in ("control", "candidate")
                                     for r in result["series"][side]["observations"]])
            for y, (side, color) in enumerate(
                [("control", "#356a9a"), ("candidate", "#a65628")]
            ):
                values = [r["wall_s"] for r in result["series"][side]["observations"]]
                interval(left, values, y, color, scale)
            left.set_yticks([0, 1], [c["control"], c["candidate"]])
            left.set_ylim(1.5, -0.5)
            left.set_xlabel(f"Included completed wall time ({unit})")
            left.set_xlim(left=0)
            if result["savings"]:
                scale, unit = time_unit(result["savings"])
                interval(right, result["savings"], 0, "#356a9a", scale)
                right.axvline(0, color="black", linestyle="--", linewidth=0.8)
                right.set_yticks([])
                right.set_ylim(-0.5, 0.5)
                right.set_xlabel(f"Paired saving ({unit})\n← slower                 faster →")
                right.set_title(f'{result["candidate_faster"]}/{result["paired_saving_s"]["n"]} pairs faster')
            else:
                right.axis("off")
                right.text(.5, .5, textwrap.fill(result["unavailable_reason"], 36),
                           ha="center", va="center", transform=right.transAxes, fontsize=9)
            save(fig, c["id"], [c["id"]])
    return artifacts

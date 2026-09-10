"""Optional scientific SVG/PNG figures over the report's validated observations.

AI-generated; imported only when the caller explicitly requests --plots.
"""

from pathlib import Path
import hashlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from review_data import stats


def interval(ax, values, y, color):
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
            fig, ax = plt.subplots(
                figsize=(10, max(2.2, 0.6 * len(model["baselines"]) + 1.1))
            )
            for y, b in enumerate(model["baselines"]):
                interval(
                    ax, [r["wall_s"] for r in b["series"]["observations"]], y, "#356a9a"
                )
            ax.set_yticks(
                range(len(model["baselines"])), [b["title"] for b in model["baselines"]]
            )
            ax.set_ylim(len(model["baselines"]) - 0.5, -0.5)
            ax.set_xlabel("Wall time at each declared boundary (seconds)")
            ax.set_xlim(left=0)
            save(fig, "baselines", [b["id"] for b in model["baselines"]])
        for c in model["comparisons"]:
            result = c["statistics"]
            fig, (left, right) = plt.subplots(
                1, 2, figsize=(10, 2.7), gridspec_kw={"width_ratios": [1.25, 1]}
            )
            for y, (side, color) in enumerate(
                [("control", "#356a9a"), ("candidate", "#a65628")]
            ):
                values = [r["wall_s"] for r in result["series"][side]["observations"]]
                interval(left, values, y, color)
            left.set_yticks([0, 1], [c["control"], c["candidate"]])
            left.set_ylim(1.5, -0.5)
            left.set_xlabel("Wall time (seconds)")
            left.set_xlim(left=0)
            interval(right, result["savings"], 0, "#356a9a")
            right.axvline(0, color="black", linestyle="--", linewidth=0.8)
            right.set_yticks([])
            right.set_ylim(-0.5, 0.5)
            right.set_xlabel(
                "Paired saving (seconds)\n← slower                 faster →"
            )
            right.set_title(
                f'{result["candidate_faster"]}/{result["paired_saving_s"]["n"]} pairs faster'
            )
            save(fig, c["id"], [c["id"]])
    return artifacts

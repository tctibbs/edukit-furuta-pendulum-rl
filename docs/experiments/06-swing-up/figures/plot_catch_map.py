# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Where a catch holds, over the arm's state at the moment the pendulum arrives.

Reads `catch_map_a1.csv`, `catch_map_a2.csv`, `catch_map_upright.csv` and
`catch_map_smooth.csv` from this experiment's `simulation/`, written by
`scripts/evaluate_catch_map.py`: 256 environments started with the pendulum in one state
near vertical and the arm on a 16 by 16 lattice of angle and rate, the policy run for
10 s, and each cell scored. A cell is a clean catch when the pendulum stayed inside
3 degrees and never passed 30, a recovery when it fell and was swung back up inside the
10 s, and a miss otherwise. The two bench arrivals of 2026-09-10 and run 9's simulated
arrival are marked on the panels they were run for.

The outcome is an ordered scale, not three identities: a miss is worse than a recovery
is worse than a clean catch. So it takes one blue ramp with lightness carrying the
order, light for a clean catch and ink for a miss, rather than the green, amber and red
this figure used to carry. Three hues at one lightness is the worst case for a
colour-blind reader and it collapses entirely in a greyscale print; three steps of one
hue survive both, and the recovery band takes a hatch on top so the middle class is
distinct by texture as well.

The layout is two by two rather than four in a row. The lattice is 16 cells across, and
at the width a reader actually sees a figure in a markdown viewer, four panels side by
side put each cell under a dozen pixels. Two by two doubles that for the same page area.

Each panel carries its clean-catch share as a number, because the comparison the
write-up makes between the panels is an area, and an eye is bad at comparing areas. The
number goes on the end of the panel's subtitle. Drawn inside the panel it needed a box
to stay legible over the cells, and that box covered nine of the sixteen cells of the
bottom row in all four panels.

    just figures 06
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

MISS, RECOVERY, CLEAN = 0, 1, 2
ORDER = (CLEAN, RECOVERY, MISS)  # the legend and the ramp read best to worst
FILL = {
    CLEAN: _style.OUTCOME_COLOURS[0],
    RECOVERY: _style.OUTCOME_COLOURS[1],
    MISS: _style.OUTCOME_COLOURS[2],
}
HATCH = dict(zip(ORDER, _style.OUTCOME_HATCH, strict=True))
HATCH_INK = _style.OUTCOME_HATCH_INK
SIDE = 16

PANELS = (
    {
        "source": "simulation/catch_map_a1.csv",
        "title": "Clock-jittered policy, bench attempt 1",
        "state": "pendulum at +2.85 deg, -0.33 rad/s",
        "arrival": (1.42, 4.21),
        "arrival_label": "bench arrival",
    },
    {
        "source": "simulation/catch_map_a2.csv",
        "title": "Clock-jittered policy, bench attempt 2",
        "state": "pendulum at +2.85 deg, -1.50 rad/s",
        "arrival": (1.04, 4.65),
        "arrival_label": "bench arrival",
    },
    {
        # "The control" is spoken for: in this write-up and in `learning_curve.png` it
        # means the run trained from random weights. This panel is the same clock
        # policy as the two above it, handed the arrival the other two are read against.
        "source": "simulation/catch_map_upright.csv",
        "title": "Clock-jittered policy, upright and still",
        "state": "pendulum upright and still",
        "arrival": None,
        "arrival_label": None,
    },
    {
        "source": "simulation/catch_map_smooth.csv",
        "title": "Corrected-plant policy, its own arrival",
        "state": "pendulum at -3.0 deg, +0.95 rad/s",
        "arrival": (-0.43, 3.69),
        "arrival_label": "simulated arrival",
    },
)


def load(path: Path) -> list[dict[str, str]]:
    """Read the map's rows."""
    with path.open() as fh:
        return list(csv.DictReader(fh))


def outcome(row: dict[str, str]) -> int:
    """Score one cell from the evaluator's columns."""
    fell = row["fell_s"] not in ("", "nan")
    held = row["held"] == "1"
    if held and not fell:
        return CLEAN
    if held:
        return RECOVERY
    return MISS


def lattice(rows: list[dict[str, str]]):
    """The 16 by 16 grid of outcomes, plus the cell pitch in each direction.

    The evaluator moves one cell of the lattice onto the arrival being studied, so the
    angle and rate columns each carry seventeen distinct values rather than sixteen.
    That displaced cell is drawn back at the lattice position it came from, which keeps
    the grid regular; it is also marked separately, at its true coordinates.
    """
    angles = sorted({round(float(r["arm_rad"]), 3) for r in rows})
    rates = sorted({round(float(r["arm_rate_rad_s"]), 3) for r in rows})
    step_a = (angles[-1] - angles[0]) / (SIDE - 1)
    step_r = (rates[-1] - rates[0]) / (SIDE - 1)
    grid = [[MISS] * SIDE for _ in range(SIDE)]
    for row in rows:
        i = round((float(row["arm_rad"]) - angles[0]) / step_a)
        j = round((float(row["arm_rate_rad_s"]) - rates[0]) / step_r)
        grid[i][j] = outcome(row)
    return grid, angles[0], rates[0], step_a, step_r


def draw_panel(ax, rows: list[dict[str, str]]) -> float:
    """Paint one map and give back the share of cells that catch cleanly."""
    grid, angle0, rate0, step_a, step_r = lattice(rows)
    for i in range(SIDE):
        for j in range(SIDE):
            value = grid[i][j]
            x = rate0 + (j - 0.5) * step_r
            y = angle0 + (i - 0.5) * step_a
            # A 2 pixel gap in the surface colour separates the cells.
            ax.add_patch(
                Rectangle(
                    (x, y),
                    step_r,
                    step_a,
                    facecolor=FILL[value],
                    edgecolor=_style.SURFACE,
                    linewidth=0.7,
                    zorder=2,
                )
            )
            if value == RECOVERY:
                ax.add_patch(
                    Rectangle(
                        (x, y),
                        step_r,
                        step_a,
                        facecolor="none",
                        edgecolor=HATCH_INK,
                        hatch=HATCH[RECOVERY],
                        linewidth=0.0,
                        zorder=3,
                    )
                )
    ax.set_xlim(rate0 - step_r / 2, rate0 + (SIDE - 0.5) * step_r)
    ax.set_ylim(angle0 - step_a / 2, angle0 + (SIDE - 0.5) * step_a)
    flat = [grid[i][j] for i in range(SIDE) for j in range(SIDE)]
    return flat.count(CLEAN) / len(flat)


def mark_arrival(ax, rows, arrival, label: str) -> None:
    """Ring the arrival the panel was run for, and say in words how it ended."""
    angle, rate = arrival
    scored = next(
        (
            outcome(r)
            for r in rows
            if abs(float(r["arm_rad"]) - angle) < 1e-6
            and abs(float(r["arm_rate_rad_s"]) - rate) < 1e-6
        ),
        None,
    )
    verdict = {CLEAN: "holds", RECOVERY: "falls and recovers", MISS: "misses"}
    ax.plot(
        [rate],
        [angle],
        marker="o",
        ms=11,
        markerfacecolor=_style.SURFACE,
        markeredgecolor=_style.INK,
        markeredgewidth=2.0,
        linestyle="none",
        zorder=6,
    )
    text = label if scored is None else f"{label}: {verdict[scored]}"
    ax.annotate(
        text,
        xy=(rate, angle),
        xytext=(-16, 24),
        textcoords="offset points",
        ha="right",
        va="center",
        fontsize=10,
        color=_style.INK,
        zorder=7,
        bbox=dict(
            boxstyle="round,pad=0.3",
            fc=_style.SURFACE,
            ec=_style.GRID,
            lw=1.0,
            alpha=0.95,
        ),
        arrowprops=dict(
            arrowstyle="-|>",
            color=_style.INK,
            lw=1.2,
            connectionstyle="arc3,rad=0.2",
            shrinkA=4,
            shrinkB=8,
        ),
    )


def main() -> int:
    """Draw the four panels and write the figure beside this script."""
    _style.apply_style()
    fig, axes = plt.subplots(2, 2, figsize=(8.6, 8.1), sharex=True, sharey=True)

    for ax, panel in zip(axes.ravel(), PANELS, strict=True):
        rows = load(EXPERIMENT / panel["source"])
        clean = draw_panel(ax, rows)
        if panel["arrival"]:
            mark_arrival(ax, rows, panel["arrival"], panel["arrival_label"])
        _style.titled(
            ax,
            panel["title"],
            f"{panel['state']}, {clean:.0%} catch cleanly",
            pad=21,
            fontsize=12.0,
            subtitle_size=10.0,
        )
        ax.grid(visible=False)
        ax.set_xticks([-6, -4, -2, 0, 2, 4, 6])
        ax.set_yticks([-2, -1, 0, 1, 2])

    for ax in axes[1]:
        ax.set_xlabel("arm rate at the arrival (rad/s)")
    for ax in axes[:, 0]:
        ax.set_ylabel("arm angle at the arrival (rad)")

    # The band is the claim all four panels carry. The clean share falls with the arm's
    # speed in every one of them, 91, 75, 88 and 100 percent under 1 rad/s against 27,
    # 23, 28 and 69 percent over 5; and with the arm out past 0.5 rad and moving faster
    # than 2 rad/s, the share is 77, 77, 83 and 100 percent when the rate is back toward
    # centre against 5, 15, 3 and 43 percent when it is outward.
    _style.figure_titled(
        fig,
        "Clean catches fill the band where the arm is slow or coming back to center",
        "Each cell starts the pendulum in the panel's state and the arm at that angle"
        " and rate, then runs the policy for 10 s.",
    )
    fig.legend(
        handles=[
            Patch(
                facecolor=FILL[value],
                edgecolor=HATCH_INK if value == RECOVERY else "none",
                hatch=HATCH[value],
                label=_style.OUTCOME_LABELS[ORDER.index(value)],
            )
            for value in ORDER
        ],
        loc="upper left",
        bbox_to_anchor=(0.0, 0.952),
        ncol=3,
        frameon=False,
        fontsize=10,
        labelcolor=_style.MUTED,
        handlelength=1.6,
        handleheight=1.2,
        columnspacing=1.8,
        borderpad=0.0,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.905), h_pad=2.4, w_pad=2.0)
    _style.save(fig, HERE / "catch_map.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

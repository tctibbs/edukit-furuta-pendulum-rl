# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""What the warm start bought, and what correcting the plant bought on top of it.

Reads `simulation/results.csv`, one row per training iteration. Ten runs are in that
ledger and plotting all ten is mush, so this draws the three that carry the argument and
names them in the legend: the control from random weights, the warm start from the
balance actor over its three seeds, and the same configuration retrained on the
corrected plant (ADR-0006) over the same three seeds. The single-change runs,
`r3-clock`, `r4-governor`, and `r6-armspeed`, are in the logbook and not here. Each
is one change from a warm run (`r6-armspeed` from `r3-clock`, the
other two from `r1-warm`) and each is one seed, so there is no band to
read them against. All three cross halfway later than any warm seed does, at 525, 395,
and 508 against the warm band's 286 to 358.

The plotted quantity is mean tilt from vertical, averaged over every environment and
every step of the iteration. The mean runs over the whole reset mixture: 40 percent of
episodes start the pendulum hanging, a quarter start it near vertical, and the rest
start it anywhere, so the curve opens near 130 and no run in the ledger reads above 142.
The from-rest diagnostic the logbook quotes, `hanging_held_half_s_frac`, was
added to the environment after `r1-scratch` and `r1-warm` had trained and is empty for
both, so it cannot carry the control; mean tilt is logged for all ten runs. Episode
length carries nothing here: once the policy stops running the rotor into its travel
bound, every episode reaches the time-out whether the pendulum went up or not.

Runs are grouped by hue rather than given one hue each. Seven lines in seven colours is
a colour-matching exercise; three bands of activity is a reading.

    just figures 06
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

# (legend label, colour, line width, the runs in the group)
GROUPS = (
    (
        "control, from random weights",
        _style.CONTROL,
        1.9,
        ("r1-scratch",),
    ),
    (
        "warm start from the balance actor, 3 seeds",
        _style.SIM,
        1.5,
        ("r1-warm", "r1-warm-seed2", "r1-warm-seed3"),
    ),
    (
        "clock-jittered, retrained on the corrected plant, 3 seeds",
        _style.CORRECTED,
        1.5,
        ("r7-smooth", "r7-smooth-seed2", "r7-smooth-seed3"),
    ),
)
HALFWAY_DEG = 45.0
SMOOTH_WINDOW = 15


def load(path: Path) -> dict[str, list[tuple[float, float]]]:
    """Iteration and mean tilt per run, in file order."""
    runs: dict[str, list[tuple[float, float]]] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            runs.setdefault(row["run"], []).append(
                (float(row["iteration"]), float(row["upright_abs_deg"]))
            )
    return runs


def smoothed(values: list[float], window: int = SMOOTH_WINDOW) -> list[float]:
    """A centred rolling mean, used only to find where a curve turns, never drawn."""
    out = []
    half = window // 2
    for i in range(len(values)):
        lo, hi = max(0, i - half), min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def first_below(series: list[tuple[float, float]], limit: float) -> float | None:
    """The first iteration whose rolling mean tilt is under `limit`, or None."""
    tilt = smoothed([v for _, v in series])
    return next((series[i][0] for i, v in enumerate(tilt) if v < limit), None)


def crossing_span(runs, names) -> str:
    """`159 to 193`, or `193`, or `never` for a group's descent through halfway."""
    hits = [first_below(runs[name], HALFWAY_DEG) for name in names if name in runs]
    hits = [h for h in hits if h is not None]
    if not hits:
        return "never"
    if len(hits) == 1 or min(hits) == max(hits):
        return f"{int(min(hits))}"
    return f"{int(min(hits))} to {int(max(hits))}"


def main() -> int:
    """Draw the curve and write it beside this script."""
    runs = load(EXPERIMENT / "simulation/results.csv")
    missing = [n for _, _, _, names in GROUPS for n in names if n not in runs]
    if missing:
        raise SystemExit(f"simulation/results.csv has no rows for {', '.join(missing)}")

    _style.apply_style()
    fig, ax = plt.subplots(figsize=(8.2, 4.7))

    for _, colour, width, names in GROUPS:
        for name in names:
            series = runs[name]
            ax.plot(
                [i for i, _ in series],
                [v for _, v in series],
                color=colour,
                lw=width,
                alpha=0.85,
                solid_joinstyle="round",
                zorder=4,
            )
        # One dot per run where its rolling mean first drops through halfway. The
        # legend gives the numbers; these put them somewhere on the plot.
        crossings = [first_below(runs[name], HALFWAY_DEG) for name in names]
        crossings = [c for c in crossings if c is not None]
        ax.plot(
            crossings,
            [HALFWAY_DEG] * len(crossings),
            marker="o",
            ms=7,
            mfc=colour,
            mec=_style.SURFACE,
            mew=1.8,
            ls="none",
            zorder=6,
        )

    _style.threshold(ax, HALFWAY_DEG, "45 deg, halfway up", x=0.012, ha="left")

    ax.set_xlabel("training iteration")
    ax.set_xlim(0, 600)
    # The band above 135 is the legend's, which is why the limit sits well over the 142
    # the highest iteration in the ledger reads. It used to carry a rule at 180 labelled
    # "hanging", and that rule was wrong twice: this mean is taken over the reset
    # mixture and cannot reach 180, and its right-hand tail came back out from behind
    # the legend's translucent box as a grey dash in the corner attached to nothing.
    ax.set_ylim(0, 196)
    ax.set_yticks([0, 45, 90, 135])
    ax.set_ylabel("mean tilt from vertical (deg)")
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)

    # The legend carries the headline number as well as the identity, so the figure
    # needs no floating box parked over the curves it is describing.
    handles = []
    for label, colour, _, names in GROUPS:
        span = crossing_span(runs, names)
        if span == "never":
            note = "never reaches halfway"
        else:
            note = f"halfway at iteration {span}"
        handles.append(Line2D([], [], color=colour, lw=2.6, label=f"{label}\n{note}"))
    ax.legend(
        handles=handles,
        loc="upper right",
        bbox_to_anchor=(1.0, 0.985),
        ncol=1,
        frameon=True,
        framealpha=0.92,
        edgecolor="none",
        facecolor=_style.SURFACE,
        fontsize=10,
        labelcolor=_style.MUTED,
        handlelength=1.9,
        labelspacing=0.7,
        borderpad=0.4,
    )
    _style.titled(
        ax,
        "Only the warm-started runs learn to hold",
        "One line per training run. Mean tilt over a reset mixture that is 40 percent"
        " hanging starts.",
    )

    _style.save(fig, HERE / "learning_curve.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

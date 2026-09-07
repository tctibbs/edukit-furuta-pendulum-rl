# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "pyyaml"]
# ///
"""The scripted swing-up handing over to the balance policy, beside the real machine.

Three panels. The top is the climb: the pendulum's angle from hanging against time, for
one simulated episode and for the reference trace Experiment 03 captured from the stock
firmware, each with its handover marked. The bottom two are every simulated handover as
a point in the plane the catch depends on, the unstable-mode coordinate `rate + 7.351 *
tilt` against the arm's rate at that instant, coloured by what followed: the first
policy on the left, the momentum-start policy on the right, on identical handovers.

Reads, beside this experiment: `handover_trace_a11.78.csv` (environment 0 of the LQR
baseline at the configured bound, every fifth 2 ms control step, physics at 4 kHz),
`handover_trace.csv` (environment 0 of the policy run at the bound the pump arrives
at, every fifth control step), `handover_episodes.csv` (one row per episode of that
run), `handover_episodes_momentum.csv` (the same for the momentum-start policy) and,
from experiment 03, `trace.tsv`. The policy-run files are drawn when present, so the
figure builds from the baseline alone. If environment 0's catch fails,
Isaac Lab resets it in place and the trace continues with a fresh episode; the climb
panel stops there.

    just figures 05
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _style  # noqa: E402

EXPERIMENT = HERE.parent
sys.path.insert(0, str(EXPERIMENT.parents[2] / "src"))

from furuta.trace import join_runs, read_trace  # noqa: E402

UNSTABLE_POLE = 7.351
RECOVERABLE_WINDOW = 1.011
# Where experiment 05's kick sweep found the policy's catch capacity: every kick through
# 0.6 rad/s recovered by every holding seed, seed 1 through 0.7.
CATCH_MEASURED = (0.6, 0.7)
GOLDEN_TRACE = EXPERIMENT.parent / "03-hardware-bringup" / "trace.tsv"


def from_hanging(tilt_rad: np.ndarray) -> np.ndarray:
    """Signed angle from hanging in degrees, wrapped to plus or minus 180.

    Wrapped rather than unwrapped on purpose: a pump strong enough to arrive is strong
    enough to carry the pendulum over the top when the handover does not fire, and an
    unwrapped trace of that spin runs to thousands of degrees and flattens everything
    else on the axis. Here a pass over the top is a jump between the two rails.
    """
    hanging = np.where(tilt_rad >= 0, tilt_rad - math.pi, tilt_rad + math.pi)
    return np.degrees(hanging)


def read_sim_trace(path: Path):
    """Time, angle from hanging and the handover instant of the simulated episode.

    Truncated at the first step after handover where `catching` drops back to 0, which
    is the trace's only marker of a termination and in-place reset.
    """
    t, tilt, catching = [], [], []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            t.append(float(row["t_s"]))
            tilt.append(float(row["tilt_rad"]))
            catching.append(int(row["catching"]))
    t = np.array(t)
    first = next((i for i, c in enumerate(catching) if c), None)
    handover = t[first] if first is not None else None
    end = len(t)
    if first is not None:
        end = next((i for i in range(first, len(t)) if not catching[i]), len(t))
    return t[:end], from_hanging(np.array(tilt[:end])), handover


def read_golden():
    """The hardware climb and the balance phase that follows it, on one time axis.

    `join_runs` places the second run one median sample after the first ends, the
    shortest seam the log supports; the handover is the end of the climb.
    """
    runs = read_trace(GOLDEN_TRACE)
    joined = join_runs(runs[:2])
    return (
        np.array(joined.time_s),
        from_hanging(np.array(joined.tilt_rad)),
        runs[0].time_s[-1],
    )


def read_episodes(path: Path):
    """Handover states and outcomes, skipping episodes that never handed over."""
    rows = []
    with path.open() as fh:
        for row in csv.DictReader(fh):
            if row["handover_s"] == "":
                continue
            rows.append(
                (
                    float(row["rotor_rate_rad_s"]),
                    float(row["mode_rad_s"]),
                    int(row["held"]),
                    int(row["terminated"]),
                )
            )
    return np.array(rows)


def main() -> int:
    """Draw both panels and write the figure beside this script."""
    baseline = EXPERIMENT / "handover_trace_a11.78.csv"
    trace = EXPERIMENT / "handover_trace.csv"
    episodes = EXPERIMENT / "handover_episodes.csv"
    for needed in (baseline, GOLDEN_TRACE):
        if not needed.exists():
            raise SystemExit(
                f"{needed} is missing. The handover files come from the training host, "
                "written by scripts/scripted_swingup.py with --trace and "
                "--episodes-out; see logbook.md."
            )

    t_base, angle_base, _ = read_sim_trace(baseline)
    t_hw, angle_hw, handover_hw = read_golden()
    t_sim = angle_sim = handover_sim = None
    if trace.exists():
        t_sim, angle_sim, handover_sim = read_sim_trace(trace)
    states = read_episodes(episodes) if episodes.exists() else np.empty((0, 4))

    momentum = EXPERIMENT / "handover_episodes_momentum.csv"
    states_momentum = read_episodes(momentum) if momentum.exists() else None

    _style.apply_style()

    fig = plt.figure(figsize=(7.5, 7.4))
    grid = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.15], hspace=0.38, wspace=0.08)
    top = fig.add_subplot(grid[0, :])
    left = fig.add_subplot(grid[1, 0])
    right = fig.add_subplot(grid[1, 1], sharey=left)

    top.plot(
        t_hw,
        angle_hw,
        color="#d55e00",
        linewidth=1.2,
        label="hardware, reference trace",
    )
    top.plot(
        t_base,
        angle_base,
        color="#999999",
        linewidth=1.0,
        label="simulation at 11.78 rad/s^2, never arrives",
    )
    if t_sim is not None:
        top.plot(
            t_sim, angle_sim, color="#0072b2", linewidth=1.2, label="simulation, env 0"
        )
    top.axvline(handover_hw, color="#d55e00", linestyle=":", linewidth=1.0)
    if handover_sim is not None:
        top.axvline(handover_sim, color="#0072b2", linestyle=":", linewidth=1.0)
    for level in (180.0, -180.0):
        top.axhline(level, color="#bbbbbb", linewidth=0.6)
    top.set_ylim(-190, 190)
    top.set_yticks([-180, -90, 0, 90, 180])
    top.set_xlabel("time (s)")
    top.set_ylabel("angle from hanging (deg)")
    top.set_xlim(0, max(t_hw[-1], (handover_sim or 0) + 5.0, 20.0))
    top.legend(
        loc="lower left", bbox_to_anchor=(0.0, 1.0), frameon=False, fontsize=7, ncol=3
    )
    top.spines[["top", "right"]].set_visible(False)

    def outcomes(ax, data, title):
        ax.axhspan(
            -CATCH_MEASURED[1], CATCH_MEASURED[1], color="#dddddd", alpha=0.5, lw=0
        )
        ax.axhspan(
            -CATCH_MEASURED[0], CATCH_MEASURED[0], color="#cccccc", alpha=0.5, lw=0
        )
        for level in (RECOVERABLE_WINDOW, -RECOVERABLE_WINDOW):
            ax.axhline(level, color="#888888", linestyle="--", linewidth=1.0)
        if data is not None and data.size:
            held = data[:, 2] == 1
            fell = (data[:, 3] == 1) & ~held
            other = ~held & ~fell
            ax.scatter(
                data[fell, 0], data[fell, 1], s=12, color="#d55e00", label="terminated"
            )
            if other.any():
                ax.scatter(
                    data[other, 0],
                    data[other, 1],
                    s=12,
                    color="#999999",
                    label="left the envelope",
                )
            ax.scatter(
                data[held, 0], data[held, 1], s=12, color="#009e73", label="held"
            )
            title = f"{title}: held {int(held.sum())} of {len(data)}"
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("arm rate at handover (rad/s)")
        ax.spines[["top", "right"]].set_visible(False)

    outcomes(left, states, "first policy")
    outcomes(right, states_momentum, "momentum-start policy")
    left.set_ylabel("unstable mode at handover (rad/s)")
    right.tick_params(labelleft=False)
    left.legend(loc="upper right", frameon=False, fontsize=7)

    out = HERE / "handover.png"
    _style.figure_titled(
        fig,
        "Handover State vs Catch Outcome",
        "Where the pump hands over, and which arrivals each policy holds.",
    )
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

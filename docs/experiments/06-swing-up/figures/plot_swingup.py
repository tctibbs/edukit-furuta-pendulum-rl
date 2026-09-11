# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""One swing-up episode in simulation: the tilt, and the arm motion that produces it.

Reads `simulation/trace_r1_warm_seed1.csv`, one row per 10 ms after decimation, written
by `scripts/record_swingup_trace.py` for the seed 1 policy from a hanging start. The
upper panel is the tilt from vertical, which starts at 180 degrees and has to reach zero
and stay there. The lower panel is the arm's angle against the travel bound, on a shared
time axis, because the arm's stroke is where the swing-up's cost sits.

The window is the first six seconds of a thirty second episode. Everything that moves
happens in the first three; the remaining twenty-four are a flat line at the bottom of
both panels, which is a result but not a shape, so it is reported as the two numbers in
the panels rather than given two thirds of the width. That keeps this figure the same
two panels on the same axes as the bench captures in `plot_bench.py`, so a reader can
compare the simulated swing-up with the measured one across pages.

    just figures 06
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

SPAN_S = 6.0
HOLD_FROM_S = 5.0  # the window the hold numbers are taken over


def load(path: Path) -> dict[str, list[float]]:
    """Read the trace into columns."""
    columns: dict[str, list[float]] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            for key, value in row.items():
                columns.setdefault(key, []).append(float(value))
    return columns


def main() -> int:
    """Draw the two panels and write the figure beside this script."""
    data = load(EXPERIMENT / "simulation/trace_r1_warm_seed1.csv")
    t = data["t_s"]
    tilt = [abs(v) for v in data["tilt_deg"]]
    arm = data["rotor_rad"]

    arrive = next((t[i] for i, v in enumerate(tilt) if v <= _style.CAPTURE_DEG), None)
    hold = [i for i, v in enumerate(t) if v >= HOLD_FROM_S]
    hold_tilt = max(tilt[i] for i in hold)
    hold_arm = [arm[i] for i in hold]
    parked = sum(hold_arm) / len(hold_arm)
    wander = max(hold_arm) - min(hold_arm)

    _style.apply_style()
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(8.2, 5.6), sharex=True, height_ratios=[1.3, 1]
    )

    # The two phases, so the shape of the episode reads before any number does.
    if arrive is not None:
        for ax in (top, bottom):
            ax.axvspan(arrive, SPAN_S, color=_style.SIM, alpha=0.07, lw=0, zorder=0)
        for centre, phase in (
            (arrive / 2, "swinging up"),
            ((arrive + SPAN_S) / 2, "holding"),
        ):
            bottom.text(
                centre,
                -2.6,
                phase,
                color=_style.MUTED,
                fontsize=10.5,
                ha="center",
                va="center",
            )

    top.plot(t, tilt, color=_style.SIM, lw=1.9, zorder=5)
    bottom.plot(t, arm, color=_style.SIM, lw=1.9, zorder=5)

    _style.tilt_axis(top)
    _style.arm_axis(bottom)

    if arrive is not None:
        for ax in (top, bottom):
            _style.event_rule(ax, arrive)
        _style.event_label(top, arrive, f"inside 3 deg at {arrive:.2f} s")

    _style.readout(
        top,
        f"from {HOLD_FROM_S:.0f} s to the end of the 30 s episode\n"
        f"the tilt never leaves {hold_tilt:.1f} deg",
        y=0.38,
    )
    _style.readout(
        bottom,
        f"the arm parks at {parked:.2f} rad and wanders\n"
        f"{wander * 1000:.0f} milliradians over the rest of the episode",
        y=0.76,
    )

    bottom.set_xlabel("time from the start of the episode (s)")
    bottom.set_xlim(0, SPAN_S)
    bottom.set_xticks([0, 1, 2, 3, 4, 5, 6])

    _style.titled(
        top,
        "From hanging to a hold, in simulation",
        "Seed 1 of the warm start, one episode from rest. The first 6 s of 30.",
    )
    fig.align_ylabels((top, bottom))
    fig.tight_layout(h_pad=0.9)
    _style.save(fig, HERE / "swingup_trace.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

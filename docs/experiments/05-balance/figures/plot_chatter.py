# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy"]
# ///
"""What raising the action-rate charge did to the command, on the real machine.

Reads two captures beside this experiment, both from the firmware's mode `b` and both
holding the pendulum for the full 30 s window: `hardware_rl_balance_a60c.tsv`, the
policy whose action-rate weight was the inherited 0.01, and
`hardware_rl_balance_a60d.tsv`, the same configuration with that weight at 0.5.

Three panels: the command over the whole hold, a second and a half of it magnified, and
the tilt the two holds produced. The first five seconds are the catch, not the hold, so
the settled statistics quoted in the write-up start at 5 s.

    just figures 05
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from plot_hardware import hold_arrays, read_capture  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _style  # noqa: E402

EXPERIMENT = HERE.parent
HOLD_DEG = 3.0
BOUND_RAD_S2 = 60.0
SETTLED_S = 5.0
# Okabe-Ito, as the other figures here use: vermillion for the policy that shakes,
# blue for the one that does not.
BEFORE, AFTER = "#d55e00", "#0072b2"
ZOOM = (15.0, 16.5)


def settled(t, series):
    """The part of a hold after the catch transient."""
    return series[t >= SETTLED_S]


def stats(t, tilt, u):
    """Reversals per second, command rms and tilt rms over the settled hold."""
    us, ts = settled(t, u), settled(t, tilt)
    span = t[t >= SETTLED_S][-1] - SETTLED_S
    sign = np.sign(us)
    nonzero = sign[sign != 0]
    reversals = int(np.sum(nonzero[:-1] * nonzero[1:] < 0))
    return (
        reversals / span,
        math.sqrt(float((us**2).mean())),
        math.sqrt(float((ts**2).mean())),
    )


def main() -> int:
    """Draw the three panels and write the figure beside this script."""
    runs = []
    for name, weight, colour in (
        ("hardware_rl_balance_a60c.tsv", 0.01, BEFORE),
        ("hardware_rl_balance_a60d.tsv", 0.5, AFTER),
    ):
        path = EXPERIMENT / name
        if not path.exists():
            raise SystemExit(
                f"{path} is missing. Both come off the board with "
                "`just hw-rl-balance`; see logbook.md."
            )
        # The full-window holds only. The a60d capture's first attempt was cut short by
        # hand at 10.9 s and would compare a disturbance against an undisturbed hold.
        full = [a for a in read_capture(path) if a["ms"] >= 29_000]
        attempt = full[0]
        t, tilt, _, u = hold_arrays(attempt)
        runs.append(
            {
                "weight": weight,
                "colour": colour,
                "t": t - t[0],
                "tilt": tilt,
                "u": u,
                "arrival": attempt["arrival"],
            }
        )

    _style.apply_style()

    fig = plt.figure(figsize=(7.5, 7.6))
    grid = fig.add_gridspec(3, 1, height_ratios=[1.0, 0.8, 0.9], hspace=0.62)
    whole, zoom, angle = (fig.add_subplot(grid[i, 0]) for i in range(3))

    for run in runs:
        label = f"action-rate weight {run['weight']}"
        whole.plot(run["t"], run["u"], color=run["colour"], linewidth=0.4, label=label)
        window = (run["t"] >= ZOOM[0]) & (run["t"] <= ZOOM[1])
        zoom.plot(
            run["t"][window],
            run["u"][window],
            color=run["colour"],
            linewidth=0.9,
            marker="o",
            markersize=1.6,
        )
        angle.plot(run["t"], run["tilt"], color=run["colour"], linewidth=0.6)

    for bound in (-BOUND_RAD_S2, BOUND_RAD_S2):
        whole.axhline(bound, color="#bbbbbb", linewidth=0.6)
    whole.axvline(SETTLED_S, color="#888888", linestyle=":", linewidth=1.0)
    whole.annotate(
        "catch    settled hold",
        xy=(SETTLED_S, 1.0),
        xycoords=("data", "axes fraction"),
        xytext=(0, 3),
        textcoords="offset points",
        ha="center",
        fontsize=7,
        color="#666666",
    )
    whole.set_ylabel("commanded rotor\nacceleration (rad/s^2)")
    whole.set_xlabel("seconds after the handover")
    whole.set_title("The whole hold", loc="left", fontsize=10.5, pad=8)
    whole.legend(fontsize=8.5, loc="lower right", framealpha=0.92)

    zoom.set_ylabel("command (rad/s^2)")
    zoom.set_xlabel(f"seconds after the handover, {ZOOM[0]:.0f} to {ZOOM[1]:.1f}")
    zoom.set_title(
        "A second and a half of it, one point per 50 ms",
        loc="left",
        fontsize=10.5,
        pad=8,
    )

    angle.axhspan(-HOLD_DEG, HOLD_DEG, color="#dddddd", alpha=0.6, lw=0)
    angle.set_ylabel("tilt from vertical (deg)")
    angle.set_xlabel("seconds after the handover")
    angle.set_title(
        f"What the pendulum did. The band is {HOLD_DEG:.0f} degrees from upright",
        loc="left",
        fontsize=10.5,
        pad=8,
    )

    out = HERE / "chatter.png"
    _style.figure_titled(
        fig,
        "Command and Tilt Across the Settled Hold",
        "The same catch and the same 60 rad/s^2 bound, at fifty times the "
        "charge on changing the command.",
    )
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")

    for run in runs:
        rate, command, tilt = stats(run["t"], run["tilt"], run["u"])
        print(
            f"  weight {run['weight']:<5} arrival {run['arrival']:+.2f} rad/s, "
            f"settled: {rate:.0f} reversals/s, command rms {command:.1f} rad/s^2, "
            f"tilt rms {tilt:.2f} deg"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

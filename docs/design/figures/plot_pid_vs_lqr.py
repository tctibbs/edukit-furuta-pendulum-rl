# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "scipy", "pyyaml"]
# ///
"""The nested PID loops and LQR recovering from the same disturbance.

Both controllers run on the same model, from the same starting tilt, under the same
actuator bound. The top panel is the pendulum, the middle is the arm underneath it, and
the bottom is what each controller asked the motor for. LQR sees all four states at once
and can spend arm travel to save pendulum angle; the nested loops see one angle each and
have to trade through a lean reference.

The PID gains were tuned against this model for the illustration. The LQR weights
and gains are the project's own, solved at run time.

    just figures
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _control as C  # noqa: E402

START_TILT_RAD = 0.035
SECONDS = 2.5


def main() -> int:
    """Draw both controllers on one disturbance."""
    model = C.load()
    start = [START_TILT_RAD, 0.0, 0.0, 0.0]
    runs = {
        "Cascaded PID loops": (
            C.simulate(model, C.pid_controller(model), SECONDS, start),
            C.PID_COLOUR,
        ),
        "State-space LQR": (
            C.simulate(model, C.lqr_controller(model), SECONDS, start),
            C.LQR_COLOUR,
        ),
    }

    plt.rcParams.update(C.PLOT_STYLE)
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(10.4, 7.4),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 0.85, 0.95], "hspace": 0.18},
    )
    tilt_ax, arm_ax, cmd_ax = axes

    for name, (run, colour) in runs.items():
        t = run["t"]
        tilt_ax.plot(t, np.degrees(run["tilt"]), color=colour, lw=2.2, label=name)
        arm_ax.plot(t, np.degrees(run["arm"]), color=colour, lw=2.2)
        cmd_ax.plot(t, run["command"], color=colour, lw=2.0)

    for ax in axes:
        ax.axhline(0, color=C.BORDER, lw=1.0)
        C.plain_axes(ax)

    tilt_ax.set_ylabel(
        "pendulum angle\nfrom upright (degrees)", fontsize=10.0, color=C.INK
    )
    tilt_ax.legend(
        loc="upper right",
        fontsize=9.5,
        frameon=True,
        framealpha=0.95,
        edgecolor=C.BORDER,
    )
    arm_ax.set_ylabel("arm angle from\ncenter (degrees)", fontsize=10.0, color=C.INK)
    cmd_ax.set_ylabel("commanded\nacceleration (rad/s^2)", fontsize=10.0, color=C.INK)
    cmd_ax.set_xlabel("seconds since release", fontsize=10.5, color=C.INK)
    cmd_ax.set_xlim(0, SECONDS)

    bound = model["a_max"]
    for sign in (1, -1):
        cmd_ax.axhline(sign * bound, color=C.MUTED, lw=1.0, ls=":")
    cmd_ax.text(
        SECONDS * 0.99,
        bound * 1.06,
        f"Actuator bound: ±{bound:.2f} rad/s^2",
        fontsize=9.2,
        color=C.MUTED,
        ha="right",
        va="bottom",
    )
    cmd_ax.set_ylim(-bound * 1.45, bound * 1.45)

    pid_arm = np.degrees(runs["Cascaded PID loops"][0]["arm"])
    lqr_arm = np.degrees(runs["State-space LQR"][0]["arm"])
    swing = lqr_arm.min()
    swing_at = runs["State-space LQR"][0]["t"][lqr_arm.argmin()]
    dip = abs(np.degrees(runs["State-space LQR"][0]["tilt"]).min())
    arm_ax.annotate(
        f"LQR lets the arm travel {abs(swing):.0f} degrees\n"
        f"and overshoots vertical once, by {dip:.1f} degrees",
        xy=(swing_at, swing),
        xytext=(SECONDS * 0.50, swing * 0.64),
        fontsize=9.2,
        color=C.LQR_COLOUR,
        ha="center",
        va="center",
        linespacing=1.45,
        arrowprops=dict(
            arrowstyle="->",
            color=C.LQR_COLOUR,
            lw=1.1,
            connectionstyle="arc3,rad=0.18",
        ),
    )
    arm_ax.annotate(
        f"PID keeps the arm within {abs(pid_arm.min()):.0f} degrees\n"
        "and the pendulum rings before settling",
        xy=(0.62, pid_arm[310]),
        xytext=(SECONDS * 0.45, 2.5),
        fontsize=9.2,
        color=C.PID_COLOUR,
        ha="center",
        va="center",
        arrowprops=dict(
            arrowstyle="->",
            color=C.PID_COLOUR,
            lw=1.1,
            connectionstyle="arc3,rad=-0.15",
        ),
    )

    fig.tight_layout()
    fig.subplots_adjust(top=0.875)
    C.titled(
        fig,
        "Disturbance response: cascaded PID versus state-space LQR",
        f"Simulated release from {math.degrees(START_TILT_RAD):.1f}-degree initial "
        f"tilt under {bound:.2f} rad/s^2 actuator acceleration limits.",
    )
    out = HERE / "pid_vs_lqr.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (PID arm to {pid_arm.min():.1f} deg, LQR {swing:.1f} deg; "
        f"peak command PID {max(abs(runs['Cascaded PID loops'][0]['command'])):.2f}, "
        f"LQR {max(abs(runs['State-space LQR'][0]['command'])):.2f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

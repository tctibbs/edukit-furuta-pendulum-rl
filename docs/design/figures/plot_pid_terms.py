# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "scipy", "pyyaml"]
# ///
"""What each of the three PID terms contributes during one recovery.

The pendulum starts about a degree off upright and the nested loops bring it back. The
top panel is the angle. The bottom splits the command into the three terms that produced
it, so each one can be read against the motion above it.

The gains here were tuned against the linearized model for this illustration. The
supplied firmware's gains are not committed to this repository.

    just figures
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _control as C  # noqa: E402

START_TILT_RAD = 0.020
SECONDS = 1.25


def main() -> int:
    """Draw the recovery and the three terms behind it."""
    model = C.load()
    run = C.simulate(
        model, C.pid_controller(model), SECONDS, [START_TILT_RAD, 0.0, 0.0, 0.0]
    )
    t = run["t"]
    tilt = [math.degrees(v) for v in run["tilt"]]
    p_term, i_term, d_term = run["terms"].T

    plt.rcParams.update(C.PLOT_STYLE)
    fig, (top, bot) = plt.subplots(
        2,
        1,
        figsize=(10.4, 6.0),
        sharex=True,
        gridspec_kw={"height_ratios": [0.62, 1.0], "hspace": 0.16},
    )

    top.axhline(0, color=C.BORDER, lw=1.0)
    top.plot(t, tilt, color=C.INK, lw=2.2)
    top.set_ylabel("pendulum angle\nfrom upright (degrees)", fontsize=10.0, color=C.INK)
    top.text(
        0.06,
        tilt[0] * 0.62,
        f"Simulated release from {tilt[0]:.1f} degrees tilt",
        fontsize=9.5,
        color=C.INK,
        va="top",
    )
    C.plain_axes(top)

    for series, colour, name, note in (
        (p_term, C.DANGER, "Proportional (P)", "penalizes current displacement error"),
        (i_term, C.SENSOR, "Integral (I)", "accumulates persistent offset"),
        (d_term, C.LQR_COLOUR, "Derivative (D)", "damps velocity"),
    ):
        bot.plot(t, series, color=colour, lw=2.0, label=f"{name}: {note}")
    bot.axhline(0, color=C.BORDER, lw=1.0)
    peak_command = max(abs(run["command"]))
    bot.text(
        SECONDS * 0.99,
        max(d_term) * 1.02,
        f"Peak combined acceleration: {peak_command:.1f} rad/s^2 "
        f"(actuator bound: ±{model['a_max']:.2f} rad/s^2)",
        fontsize=9.2,
        color=C.MUTED,
        ha="right",
        va="top",
    )
    bot.annotate(
        "Integral term remains near zero during brief transients;\nsteady offsets take "
        "longer to accumulate",
        xy=(0.42, i_term[210]),
        xytext=(0.66, 3.9),
        fontsize=9.2,
        color=C.SENSOR,
        ha="center",
        va="center",
        linespacing=1.45,
        arrowprops=dict(
            arrowstyle="->", color=C.SENSOR, lw=1.1, connectionstyle="arc3,rad=0.2"
        ),
    )
    bot.set_ylabel("contribution to the\ncommand (rad/s^2)", fontsize=10.0, color=C.INK)
    bot.set_xlabel("seconds since release", fontsize=10.5, color=C.INK)
    bot.set_xlim(0, SECONDS)
    bot.legend(
        loc="lower right",
        fontsize=9.5,
        frameon=True,
        framealpha=0.95,
        edgecolor=C.BORDER,
    )
    C.plain_axes(bot)

    fig.tight_layout()
    fig.subplots_adjust(top=0.84)
    C.titled(
        fig,
        "PID control term decomposition during pendulum recovery",
        "Proportional, integral, and derivative components sum to form total "
        "commanded acceleration.",
    )
    out = HERE / "pid_terms.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (peak tilt {max(abs(v) for v in tilt):.2f} deg, "
        f"peak |P| {max(abs(p_term)):.1f}, |I| {max(abs(i_term)):.1f}, "
        f"|D| {max(abs(d_term)):.1f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

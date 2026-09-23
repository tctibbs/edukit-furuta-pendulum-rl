# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "scipy", "pyyaml"]
# ///
"""Where the machine's poles sit before a controller, and where LQR puts them.

A pole in the right half of the plane grows. The pendulum near upright has one. That
pole is the whole reason the machine needs a controller. LQR moves all four into the
left half, and the distance each one sits from the imaginary axis is how fast that part
of the response dies away.

Numbers come from `config/edukit.yaml` and the Riccati solve at run time.

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


def main() -> int:
    """Draw the open-loop and closed-loop poles side by side."""
    model = C.load()
    a, b, gains = model["a"], model["b"], model["gains"]
    openloop = np.linalg.eigvals(a)
    closed = np.linalg.eigvals(a - b @ gains.reshape(1, 4))

    plt.rcParams.update(C.PLOT_STYLE)
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.6, 4.6), sharey=True)

    for ax, poles, colour, name in (
        (left, openloop, C.DANGER, "Open-loop plant (uncontrolled)"),
        (right, closed, C.LQR_COLOUR, "Closed-loop LQR"),
    ):
        ax.axhline(0, color=C.BORDER, lw=1.0, zorder=1)
        ax.axvline(0, color=C.INK, lw=1.4, zorder=2)
        ax.axvspan(0, 10, color=C.DANGER, alpha=0.07, lw=0, zorder=0)
        ax.plot(
            poles.real,
            poles.imag,
            "x",
            color=colour,
            markersize=11,
            markeredgewidth=2.4,
            zorder=4,
        )
        ax.set_xlim(-9.5, 9.5)
        ax.set_ylim(-3.2, 3.2)
        ax.set_xlabel("growth rate (1/s)", fontsize=10.5, color=C.INK)
        ax.set_title(
            name, loc="left", fontsize=11.5, color=C.INK, fontweight="bold", pad=8
        )
        C.plain_axes(ax)

    left.set_ylabel("oscillation (rad/s)", fontsize=10.5, color=C.INK)
    unstable = max(p.real for p in openloop)
    left.annotate(
        f"Unstable pole grows\nat {unstable:.2f} per second,\ndoubling tilt every "
        f"{math.log(2) / unstable * 1000:.0f} ms",
        xy=(unstable, 0.0),
        xytext=(3.4, 2.0),
        fontsize=9.2,
        color=C.DANGER,
        ha="center",
        va="center",
        linespacing=1.45,
        arrowprops=dict(
            arrowstyle="->", color=C.DANGER, lw=1.1, connectionstyle="arc3,rad=-0.25"
        ),
    )
    left.text(
        4.6,
        -2.75,
        "Right half-plane: unstable divergence",
        fontsize=9.2,
        color=C.DANGER,
        ha="center",
    )
    fastest = min(p.real for p in closed)
    slowest = max(p.real for p in closed)
    right.annotate(
        f"Pendulum mode decays\nat {abs(fastest):.1f} per second",
        xy=(fastest, closed[np.argmin(closed.real)].imag),
        xytext=(-6.4, 2.2),
        fontsize=9.2,
        color=C.LQR_COLOUR,
        ha="center",
        va="center",
        linespacing=1.45,
        arrowprops=dict(
            arrowstyle="->", color=C.LQR_COLOUR, lw=1.1, connectionstyle="arc3,rad=0.25"
        ),
    )
    right.annotate(
        f"Arm mode recenters\nat {abs(slowest):.2f} per second",
        xy=(slowest, -abs(closed[np.argmax(closed.real)].imag)),
        xytext=(-4.2, -2.2),
        fontsize=9.2,
        color=C.LQR_COLOUR,
        ha="center",
        va="center",
        linespacing=1.45,
        arrowprops=dict(
            arrowstyle="->", color=C.LQR_COLOUR, lw=1.1, connectionstyle="arc3,rad=0.18"
        ),
    )

    fig.tight_layout()
    fig.subplots_adjust(top=0.76)
    C.titled(
        fig,
        "Open-loop versus closed-loop poles on the complex plane",
        "Poles in the right half-plane diverge exponentially; state feedback shifts "
        "all poles to stable decay regions.",
    )
    out = HERE / "stability.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (unstable pole {unstable:.3f}, "
        f"closed loop {np.round(closed, 3)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

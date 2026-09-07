# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Why pendulum position enters the observation as a unit vector rather than an angle.

Left, the encoding: an angle measured from upright maps to one point on the unit circle,
and the two coordinates of that point are what the policy reads. Right, the reason: a
raw angle has to be wrapped to a finite interval somewhere, and at that seam it steps a
full turn while the pendulum is moving smoothly through it. The seam sits at hanging,
which the swing-up task traverses on every attempt.

The termination band is `max_pendulum_angle_rad` in `src/furuta/env.py`.

    just figures
"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
from pathlib import Path  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Wedge  # noqa: E402

HERE = Path(__file__).resolve().parent

INK = "#1a2733"
MUTED = "#5a6b7a"
BORDER = "#c9d2db"
SENSOR = "#1f6feb"
DANGER = "#d64545"
GOOD = "#2e9e5b"

MAX_PENDULUM_ANGLE_RAD = 0.35  # env.py, the tilt termination for the balance tasks
SAMPLE_DEG = 55.0  # an angle far enough out that both projections are readable


def draw_circle(ax) -> None:
    """The unit circle, with one angle resolved into its two coordinates."""
    theta = math.radians(SAMPLE_DEG)
    cx, cy = math.cos(theta), math.sin(theta)

    band = math.degrees(MAX_PENDULUM_ANGLE_RAD)
    ax.add_patch(
        Wedge((0, 0), 1.0, -band, band, facecolor=GOOD, alpha=0.16, lw=0, zorder=1)
    )

    ring = np.linspace(0, 2 * math.pi, 400)
    ax.plot(np.cos(ring), np.sin(ring), color=BORDER, lw=1.8, zorder=2)
    ax.axhline(0, color=BORDER, lw=1.0, zorder=1)
    ax.axvline(0, color=BORDER, lw=1.0, zorder=1)

    arc = np.linspace(0, theta, 80)
    ax.plot(0.28 * np.cos(arc), 0.28 * np.sin(arc), color=INK, lw=1.6, zorder=4)
    ax.text(
        0.40 * math.cos(theta / 2),
        0.40 * math.sin(theta / 2),
        r"$\theta$",
        fontsize=13,
        color=INK,
        ha="center",
        va="center",
        zorder=5,
    )

    ax.plot([0, cx], [0, cy], color=SENSOR, lw=2.4, zorder=4)
    ax.plot([cx], [cy], "o", color=SENSOR, markersize=9, zorder=5)
    ax.plot([cx, cx], [0, cy], color=SENSOR, lw=1.3, ls=":", zorder=3)
    ax.plot([0, cx], [cy, cy], color=SENSOR, lw=1.3, ls=":", zorder=3)
    ax.text(
        cx,
        -0.09,
        r"$\cos\theta$",
        fontsize=11,
        color=SENSOR,
        ha="center",
        va="top",
        zorder=5,
    )
    ax.text(
        -0.06,
        cy,
        r"$\sin\theta$",
        fontsize=11,
        color=SENSOR,
        ha="right",
        va="center",
        zorder=5,
    )

    ax.plot([1.0], [0], "s", color=GOOD, markersize=8, zorder=5)
    ax.text(
        1.12,
        0.0,
        f"upright\n$\\theta = 0$\n±{band:.0f} degree band",
        fontsize=9.5,
        color=GOOD,
        ha="left",
        va="center",
        linespacing=1.45,
        zorder=5,
    )
    ax.plot([-1.0], [0], "^", color=DANGER, markersize=9, zorder=5)
    ax.text(
        -1.07,
        0.0,
        "hanging\n$\\theta = \\pm\\pi$",
        fontsize=9.5,
        color=DANGER,
        ha="right",
        va="center",
        linespacing=1.45,
        zorder=5,
    )

    ax.set_xlim(-1.75, 1.75)
    ax.set_ylim(-1.32, 1.32)
    ax.set_aspect("equal")
    ax.axis("off")


def draw_sweep(wrap_ax, unit_ax) -> None:
    """One full rotation, drawn twice: wrapped to an angle, and as two coordinates."""
    turn = np.linspace(-360.0, 360.0, 1600)
    wrapped = (turn + 180.0) % 360.0 - 180.0
    # Break the line at each seam so the step draws as a gap, not a vertical stroke.
    seams = np.abs(np.diff(wrapped)) > 180.0
    broken = wrapped.astype(float).copy()
    broken[:-1][seams] = np.nan

    wrap_ax.plot(turn, broken, color=DANGER, lw=2.4, zorder=4)
    wrap_ax.set_ylim(-260, 260)
    wrap_ax.set_yticks([-180, 0, 180])
    wrap_ax.set_ylabel("wrapped angle\n(degrees)", fontsize=10.0, color=INK)
    wrap_ax.annotate(
        "",
        xy=(205, 180),
        xytext=(205, -180),
        arrowprops=dict(arrowstyle="<->", color=DANGER, lw=1.5),
    )
    wrap_ax.text(
        272,
        232,
        "360-degree boundary step",
        fontsize=9.5,
        color=DANGER,
        fontweight="bold",
        ha="center",
        va="top",
    )

    unit_ax.plot(turn, np.cos(np.radians(turn)), color=GOOD, lw=2.2, zorder=3)
    unit_ax.plot(
        turn, np.sin(np.radians(turn)), color=SENSOR, lw=2.2, ls="--", zorder=3
    )
    unit_ax.set_ylim(-1.55, 1.55)
    unit_ax.set_yticks([-1, 0, 1])
    unit_ax.set_ylabel("unit vector", fontsize=10.0, color=INK)
    unit_ax.text(
        -352, 1.12, r"$\cos\theta$", fontsize=11, color=GOOD, fontweight="bold"
    )
    unit_ax.text(
        -262, -1.42, r"$\sin\theta$", fontsize=11, color=SENSOR, fontweight="bold"
    )

    for ax in (wrap_ax, unit_ax):
        for seam in (-180.0, 180.0):
            ax.axvline(seam, color=DANGER, lw=1.0, ls=":", zorder=2)
        ax.set_xlim(-360, 360)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    wrap_ax.tick_params(labelbottom=False)
    unit_ax.set_xticks([-360, -180, 0, 180, 360])
    unit_ax.set_xticklabels(
        ["-360", "-180\nhanging", "0\nupright", "180\nhanging", "360"]
    )
    unit_ax.set_xlabel(
        "pendulum position from upright (degrees)", fontsize=10.5, color=INK
    )


def main() -> int:
    """Draw the encoding and the seam it avoids."""
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        }
    )
    fig = plt.figure(figsize=(11.6, 4.9))
    grid = fig.add_gridspec(2, 2, width_ratios=[0.78, 1.22], hspace=0.16, wspace=0.24)
    draw_circle(fig.add_subplot(grid[:, 0]))
    draw_sweep(fig.add_subplot(grid[0, 1]), fig.add_subplot(grid[1, 1]))

    fig.tight_layout()
    fig.subplots_adjust(top=0.79)
    fig.text(
        0.012,
        0.985,
        "Pendulum position representation: wrapped angle versus unit vector",
        ha="left",
        va="top",
        fontsize=13.5,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.012,
        0.905,
        "Full rotation from upright. Discontinuity occurs at downward hanging.",
        ha="left",
        va="top",
        fontsize=10.5,
        color=MUTED,
    )

    out = HERE / "angle_encoding.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (band ±{math.degrees(MAX_PENDULUM_ANGLE_RAD):.0f} deg, "
        f"sample angle {SAMPLE_DEG:.0f} deg)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

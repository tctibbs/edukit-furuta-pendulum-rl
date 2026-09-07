# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "pyyaml"]
# ///
"""How many encoder marks go by in one control step, and in sixteen.

The encoder reports whole counts. Near upright the pendulum crosses a fraction of a
count per control step, so subtracting two adjacent samples returns either no counts or
one count, and nothing in between. A longer window has enough counts inside it to
measure a rate.

Every number is derived from `config/edukit.yaml` and the unstable mode at run time.

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
ROOT = HERE.resolve().parents[2]  # docs/adrs/figures -> repository root

INK = "#1a2733"
MUTED = "#5a6b7a"
BORDER = "#c9d2db"
DANGER = "#d64545"
GOOD = "#2e9e5b"
SENSOR = "#1f6feb"

MODE_COEFF = 7.351  # inverted natural frequency, rad/s
START_ANGLE_RAD = 0.010  # release just off vertical
START_RATE_RAD_S = 0.30  # drifting, well inside the recoverable set


def bracket(ax, x0: float, x1: float, y: float, color: str) -> None:
    """Draw a span marker between two times."""
    ax.annotate(
        "",
        xy=(x0, y),
        xytext=(x1, y),
        arrowprops=dict(arrowstyle="|-|,widthA=0.5,widthB=0.5", color=color, lw=1.6),
    )


def main() -> int:
    """Draw the counts available to a one-step difference and to a 16-step window."""
    sys.path.insert(0, str(ROOT / "src"))
    from furuta.parameters import FurutaParameters

    p = FurutaParameters.from_yaml(ROOT / "config" / "edukit.yaml")
    quantum = p.rad_per_encoder_count
    dt = p.control_dt_s
    window = 16
    w = MODE_COEFF

    t = np.arange(0.0, 0.043, dt)
    angle = START_ANGLE_RAD * np.cosh(w * t) + (START_RATE_RAD_S / w) * np.sinh(w * t)
    counted = np.round(angle / quantum)
    step = np.arange(len(t), dtype=float)

    # A 16-sample least-squares slope over the same counts, which is what ships.
    offsets = np.arange(window) - (window - 1) / 2.0
    weights = offsets / (dt * (offsets**2).sum())
    fitted = counted[1 : 1 + window] * quantum @ weights

    flat = 5  # a step where the count does not move
    tick = 2  # the step where it does
    span_a, span_b = 1, window  # the window the fit sees

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
    fig, ax = plt.subplots(figsize=(10.4, 5.2))

    ax.plot(step, angle / quantum, color=MUTED, lw=1.6, ls="--", zorder=3)
    ax.step(step, counted, where="post", color=SENSOR, lw=2.4, zorder=4)
    ax.plot(step, counted, "o", color=SENSOR, markersize=4.5, zorder=5)
    ax.text(
        17.0,
        6.5,
        "Encoder quantized count",
        fontsize=9.5,
        color=SENSOR,
        ha="center",
        va="top",
    )
    ax.text(
        10.0,
        7.35,
        "Continuous angle",
        fontsize=9.5,
        color=MUTED,
        ha="center",
    )

    # One control step that lands on a tick, and one that does not.
    for i, label, rate_text in (
        (tick, "1 mark", f"yields {quantum / dt:.3f} rad/s"),
        (flat, "0 marks", "yields 0 rad/s"),
    ):
        bracket(ax, step[i], step[i + 1], 8.5, DANGER)
        for edge in (i, i + 1):
            ax.plot(
                [step[edge], step[edge]],
                [counted[edge], 8.5],
                color=DANGER,
                lw=0.9,
                ls=":",
                zorder=2,
            )
        ax.text(
            (step[i] + step[i + 1]) / 2,
            8.75,
            f"{label}\n{rate_text}",
            fontsize=9.5,
            color=DANGER,
            ha="center",
            va="bottom",
            fontweight="bold",
            linespacing=1.4,
        )
    ax.text(
        (step[tick] + step[flat + 1]) / 2,
        10.45,
        "Single control step: two discrete outcomes",
        fontsize=10.0,
        color=DANGER,
        ha="center",
        va="bottom",
    )

    # The window the shipped estimator uses.
    marks = counted[span_b] - counted[span_a]
    span_ms = (span_b - span_a) * dt * 1000.0
    bracket(ax, step[span_a], step[span_b], 2.6, GOOD)
    for edge in (span_a, span_b):
        ax.plot(
            [step[edge], step[edge]],
            [2.6, counted[edge]],
            color=GOOD,
            lw=0.9,
            ls=":",
            zorder=2,
        )
    ax.text(
        (step[span_a] + step[span_b]) / 2,
        2.25,
        f"Sixteen-sample regression window spanning {span_ms:.0f} ms captures "
        f"{marks:.0f} marks, resolving {fitted:.2f} rad/s",
        fontsize=10.0,
        color=GOOD,
        ha="center",
        va="top",
    )

    ax.set_xlim(-0.6, 21.6)
    ax.set_ylim(1.4, 11.6)
    ax.set_yticks(range(4, 10))
    ax.set_ylabel("encoder count", fontsize=10.5, color=INK)
    ax.set_xticks(range(0, 22, 2))
    ax.set_xlabel(
        f"Control step after release ({dt * 1000:.0f} ms step duration)",
        fontsize=10.5,
        color=INK,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)
    ax.spines["left"].set_color(BORDER)

    fig.tight_layout()
    fig.subplots_adjust(top=0.82)
    fig.text(
        0.012,
        0.985,
        "Encoder count resolution across single-step and windowed rate estimates",
        ha="left",
        va="top",
        fontsize=13.5,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.012,
        0.915,
        f"Pendulum drifting at {START_RATE_RAD_S} rad/s near upright traverses "
        f"{START_RATE_RAD_S * dt / quantum:.2f} marks per control step.",
        ha="left",
        va="top",
        fontsize=10.5,
        color=MUTED,
    )

    out = HERE / "velocity_resolution.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (one mark {math.degrees(quantum):.2f} deg, "
        f"{START_RATE_RAD_S * dt / quantum:.2f} marks per step, "
        f"{marks:.0f} marks per window, fit {fitted:.3f} rad/s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

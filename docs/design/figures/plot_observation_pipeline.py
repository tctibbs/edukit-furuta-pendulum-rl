# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "pyyaml"]
# ///
"""How the two hardware counters become the policy's five observations.

One control step, left to right. The encoder's count reaches the observation vector two
ways: wrapped straight into a unit vector, and through the slope fit that reconstructs a
rate. The microstep counter does the same for the arm. ADR-0005 carries the reason
the slope fit is in the middle rather than a two-sample difference.

Every number here is derived from `config/edukit.yaml` at run time.

    just figures
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.resolve().parents[2]  # docs/design/figures -> repository root

INK = "#1a2733"
MUTED = "#5a6b7a"
FAINT = "#8a9aa8"
SENSOR = "#1f6feb"
STAGE = "#e8833a"
GOOD = "#2e9e5b"
DIRECT = "#4b5563"


def draw_box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str,
    edge_color: str,
    bg_color: str,
    font_size_body: float = 9.2,
) -> None:
    """Draw a rounded card stage."""
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=1.6,
            edgecolor=edge_color,
            facecolor=bg_color,
            zorder=3,
        )
    )
    ax.text(
        x + w / 2,
        y + h - 0.06,
        title,
        ha="center",
        va="top",
        fontsize=11.0,
        color=edge_color,
        fontweight="bold",
        zorder=4,
    )
    ax.text(
        x + w / 2,
        y + h - 0.165,
        body,
        ha="center",
        va="top",
        fontsize=font_size_body,
        color=INK,
        zorder=4,
        linespacing=1.55,
    )


def draw_arrow(
    ax,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: str,
    lw: float = 1.6,
    connectionstyle: str = "arc3,rad=0.0",
) -> None:
    """Draw a directional connecting arrow."""
    ax.add_patch(
        FancyArrowPatch(
            (x0, y0),
            (x1, y1),
            connectionstyle=connectionstyle,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=lw,
            color=color,
            zorder=2,
        )
    )


def lane_label(ax, x: float, y: float, text: str, color: str) -> None:
    """Label a bypass lane without boxing it."""
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=9.0,
        color=color,
        zorder=4,
        path_effects=[pe.withStroke(linewidth=3.0, foreground="white")],
    )


def main() -> int:
    """Draw the counters-to-observation pipeline."""
    sys.path.insert(0, str(ROOT / "src"))
    from furuta.parameters import FurutaParameters

    p = FurutaParameters.from_yaml(ROOT / "config" / "edukit.yaml")
    rad_per_count = p.rad_per_encoder_count
    steps_per_rad = p.microsteps_per_rev / (2 * math.pi)
    dt = p.control_dt_s
    window = 16
    span_ms = (window - 1) * dt * 1000.0
    lag_ms = span_ms / 2.0

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
    fig, ax = plt.subplots(figsize=(11.0, 4.9))
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")

    # Sensors, left column.
    draw_box(
        ax,
        0.015,
        0.555,
        0.245,
        0.355,
        "Optical encoder",
        f"{p.encoder_counts_per_rev} counts per revolution\n"
        f"Resolution: {rad_per_count:.5f} rad/count",
        SENSOR,
        "#f0f6ff",
    )
    draw_box(
        ax,
        0.015,
        0.075,
        0.245,
        0.355,
        "Microstep counter",
        f"{steps_per_rad:.1f} microsteps per radian\nNo dedicated rotor encoder",
        SENSOR,
        "#f0f6ff",
    )

    # Slope fit, center.
    draw_box(
        ax,
        0.375,
        0.315,
        0.270,
        0.355,
        "Least-squares slope fit",
        f"Linear regression filter, precomputed weights\n"
        f"{window} samples spanning {span_ms:.0f} ms\n"
        f"Introduces {lag_ms:.0f} ms group delay",
        STAGE,
        "#fff9f5",
    )

    # Observation vector, right column. The five rows are drawn as two aligned
    # columns so the symbols and their names each line up.
    draw_box(ax, 0.735, 0.256, 0.250, 0.585, "Observation vector", "", GOOD, "#f2fbf5")
    rows = [
        (r"$\cos\theta$", "pendulum position, cosine"),
        (r"$\sin\theta$", "pendulum position, sine"),
        (r"$\dot{\theta}$", "pendulum velocity"),
        (r"$\phi$", "rotor position"),
        (r"$\dot{\phi}$", "rotor velocity"),
    ]
    for i, (symbol, name) in enumerate(rows):
        y = 0.640 - i * 0.081
        ax.text(
            0.828,
            y,
            symbol,
            ha="right",
            va="center",
            fontsize=11.0,
            color=INK,
            zorder=4,
        )
        ax.text(
            0.845, y, name, ha="left", va="center", fontsize=9.6, color=INK, zorder=4
        )

    # Bypass lanes: counts and microsteps reach the vector without a fit. Both run
    # clear of the slope-fit card rather than across it.
    draw_arrow(ax, 0.263, 0.845, 0.730, 0.700, DIRECT, lw=1.4)
    lane_label(ax, 0.497, 0.876, r"Map count to $[\cos\theta, \sin\theta]$", DIRECT)
    draw_arrow(ax, 0.263, 0.140, 0.730, 0.290, DIRECT, lw=1.4)
    lane_label(ax, 0.497, 0.108, "Scale step count to radians", DIRECT)

    # Both counters feed the fit.
    draw_arrow(ax, 0.263, 0.660, 0.370, 0.585, STAGE)
    draw_arrow(ax, 0.263, 0.290, 0.370, 0.395, STAGE)
    lane_label(ax, 0.317, 0.658, "samples", STAGE)
    lane_label(ax, 0.317, 0.292, "samples", STAGE)

    # The fit supplies both rates.
    draw_arrow(ax, 0.648, 0.478, 0.730, 0.478, GOOD, lw=1.9)
    lane_label(ax, 0.689, 0.527, r"$\dot{\theta}, \dot{\phi}$", GOOD)

    fig.tight_layout()
    fig.subplots_adjust(top=0.855, bottom=0.02)
    fig.text(
        0.012,
        0.985,
        "Observation pipeline: hardware counters to observation vector",
        ha="left",
        va="top",
        fontsize=13.5,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.012,
        0.915,
        f"Single {dt * 1000:.0f} ms control step. "
        "Hardware counters track position only; online slope regression "
        "reconstructs angular rates.",
        ha="left",
        va="top",
        fontsize=10.5,
        color=MUTED,
    )

    out = HERE / "observation_pipeline.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (one count {rad_per_count:.5f} rad, "
        f"{steps_per_rad:.1f} microsteps/rad, window {span_ms:.0f} ms, "
        f"lag {lag_ms:.0f} ms)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

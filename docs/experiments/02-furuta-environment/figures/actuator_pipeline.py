# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Draw the stepper motor emulation and sensing pipeline.

Illustrates the discrete acceleration-to-position pipeline alongside the
quantized observation path.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent

INK = "#1a2733"
MUTED = "#5a6b7a"
ACCENT_BLUE = "#1f6feb"
ACCENT_ORANGE = "#e8833a"
ACCENT_GREEN = "#2e9e5b"
PURPLE = "#6366f1"


def draw_box(
    ax: plt.Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    subtitle: str | None = None,
    color: str = ACCENT_BLUE,
    fill: str = "#ffffff",
) -> float:
    """Draw a rounded labeled block centered vertically at y."""
    box = FancyBboxPatch(
        (x, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.06,rounding_size=0.10",
        facecolor=fill,
        edgecolor=color,
        linewidth=1.4,
        zorder=3,
    )
    ax.add_patch(box)
    if subtitle:
        ax.text(
            x + w / 2,
            y + 0.12,
            title,
            ha="center",
            va="center",
            fontsize=8.5,
            fontweight="bold",
            color=INK,
            zorder=4,
        )
        ax.text(
            x + w / 2,
            y - 0.16,
            subtitle,
            ha="center",
            va="center",
            fontsize=7.2,
            color=MUTED,
            zorder=4,
        )
    else:
        ax.text(
            x + w / 2,
            y,
            title,
            ha="center",
            va="center",
            fontsize=8.2,
            fontweight="bold",
            color=INK,
            zorder=4,
        )
    return x + w


def draw_arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    label: str | None = None,
    color: str = INK,
    label_y_offset: float = 0.12,
) -> None:
    """Draw a directed signal arrow with optional label."""
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=10,
            color=color,
            linewidth=1.2,
            zorder=2,
        )
    )
    if label:
        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2 + label_y_offset
        ax.text(
            mid_x,
            mid_y,
            label,
            ha="center",
            va="bottom",
            fontsize=7.2,
            color=MUTED,
            zorder=4,
        )


def main() -> None:
    """Generate and save the actuator pipeline architecture diagram."""
    fig, ax = plt.subplots(figsize=(12.4, 5.0), dpi=180)
    ax.set_xlim(0, 12.4)
    ax.set_ylim(-0.2, 4.6)
    ax.axis("off")

    # Background groupings
    # 1. Control loop (500 Hz)
    rect_500 = FancyBboxPatch(
        (0.15, 2.1),
        8.0,
        2.2,
        boxstyle="round,pad=0.12",
        facecolor="#f8fafc",
        edgecolor="#cbd5e1",
        linestyle="--",
        linewidth=1.2,
        zorder=1,
    )
    ax.add_patch(rect_500)
    ax.text(
        0.35,
        4.05,
        "Microcontroller Control Cycle (500 Hz, dt = 2 ms)",
        fontsize=9,
        fontweight="bold",
        color="#475569",
        zorder=2,
    )

    # 2. Physics simulation (1000 Hz)
    rect_phys = FancyBboxPatch(
        (8.35, 2.1),
        3.9,
        2.2,
        boxstyle="round,pad=0.12",
        facecolor="#fffaf5",
        edgecolor="#fed7aa",
        linestyle="--",
        linewidth=1.2,
        zorder=1,
    )
    ax.add_patch(rect_phys)
    ax.text(
        8.55,
        4.05,
        "PhysX Substeps (1000 Hz, dt = 1 ms)",
        fontsize=9,
        fontweight="bold",
        color="#c2410c",
        zorder=2,
    )

    # 3. Observation sensing pipeline
    rect_obs = FancyBboxPatch(
        (0.15, 0.0),
        12.1,
        1.8,
        boxstyle="round,pad=0.12",
        facecolor="#f0fdf4",
        edgecolor="#bbf7d0",
        linestyle="--",
        linewidth=1.2,
        zorder=1,
    )
    ax.add_patch(rect_obs)
    ax.text(
        0.35,
        1.55,
        "Hardware Feedback & Sensor Discretization",
        fontsize=9,
        fontweight="bold",
        color="#166534",
        zorder=2,
    )

    # Top flow: Actuator pipeline
    y_act = 3.1
    # Input
    draw_arrow(ax, (0.25, y_act), (0.85, y_act))
    ax.text(
        0.55,
        y_act + 0.18,
        "action",
        fontsize=8,
        ha="center",
        color=INK,
        fontweight="bold",
    )
    ax.text(0.55, y_act - 0.22, "[-1, 1]", fontsize=7, ha="center", color=MUTED)

    # Box 1: Scale Accel
    draw_box(ax, 0.85, y_act, 1.15, 0.85, "Scale Demand", "100 rad/s^2", ACCENT_BLUE)
    draw_arrow(ax, (2.0, y_act), (2.55, y_act), "alpha")

    # Box 2: Velocity integration
    draw_box(ax, 2.55, y_act, 1.15, 0.85, "Velocity Step", "speed clamp", ACCENT_BLUE)
    draw_arrow(ax, (3.7, y_act), (4.25, y_act), "omega")

    # Box 3: Position integration
    draw_box(ax, 4.25, y_act, 1.15, 0.85, "Position Step", "integrate dt", ACCENT_BLUE)
    draw_arrow(ax, (5.4, y_act), (5.95, y_act), "q_cont")

    # Box 4: Microstep lattice
    draw_box(ax, 5.95, y_act, 1.3, 0.85, "Microstep Grid", "1/3200 rev", ACCENT_BLUE)
    draw_arrow(ax, (7.25, y_act), (8.55, y_act), "q_target")

    # Box 5: DriveAPI
    draw_box(
        ax, 8.55, y_act, 1.45, 0.85, "PhysX DriveAPI", "K=1e5, D=50", ACCENT_ORANGE
    )
    draw_arrow(ax, (10.0, y_act), (10.6, y_act), "torque")

    # Box 6: Articulation
    draw_box(
        ax,
        10.6,
        y_act,
        1.45,
        0.85,
        "Reduced\nArticulation",
        "2 substeps",
        ACCENT_ORANGE,
    )

    # Bottom flow: Sensing
    y_sens = 0.75
    # Pendulum physical angle
    draw_arrow(ax, (0.3, y_sens + 0.35), (1.1, y_sens + 0.35))
    ax.text(
        0.7,
        y_sens + 0.52,
        "theta",
        fontsize=8,
        ha="center",
        color=INK,
        fontweight="bold",
    )

    # Box: Encoder
    draw_box(
        ax,
        1.1,
        y_sens + 0.35,
        1.6,
        0.58,
        "Encoder Quantize",
        "2400 counts/rev",
        ACCENT_GREEN,
    )
    draw_arrow(ax, (2.7, y_sens + 0.35), (3.55, y_sens + 0.35), "theta_k")

    # Box: Differencing
    draw_box(
        ax,
        3.55,
        y_sens + 0.35,
        1.6,
        0.58,
        "Finite Difference",
        "velocity estimate",
        ACCENT_GREEN,
    )
    draw_arrow(ax, (5.15, y_sens + 0.35), (6.2, y_sens + 0.15), "dtheta_k")

    # Rotor physical angle (open loop!)
    draw_arrow(ax, (0.3, y_sens - 0.35), (1.1, y_sens - 0.35))
    ax.text(
        0.7,
        y_sens - 0.18,
        "rotor cmd",
        fontsize=7.8,
        ha="center",
        color=INK,
        fontweight="bold",
    )

    draw_box(
        ax,
        1.1,
        y_sens - 0.35,
        4.05,
        0.55,
        "Open-Loop Stepper Accumulator",
        "counts microsteps (no rotor encoder)",
        "#64748b",
    )
    draw_arrow(ax, (5.15, y_sens - 0.35), (6.2, y_sens - 0.15), "phi_k")

    # Observation vector assembling
    draw_box(
        ax,
        6.2,
        y_sens,
        2.3,
        0.95,
        "Observation Vector",
        "[theta, phi, dtheta, dphi]",
        ACCENT_GREEN,
    )
    draw_arrow(ax, (8.5, y_sens), (9.4, y_sens), "obs")

    # Policy
    draw_box(ax, 9.4, y_sens, 1.8, 0.95, "RL Policy", "DirectRLEnv", PURPLE)

    plt.tight_layout()
    out_path = HERE / "actuator_pipeline.png"
    plt.savefig(out_path, dpi=180, bbox_inches="tight")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

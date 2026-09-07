# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "pyyaml"]
# ///
"""The coordinate conventions behind the observation vector, in two views.

One view cannot show both angles. The pendulum tilts in a vertical plane and the arm
sweeps in a horizontal one, so a side elevation makes the tilt readable and hides the
sweep, and a plan view does the reverse. Both are drawn to the measured arm and pendulum
lengths in `config/edukit.yaml`.

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
from matplotlib.patches import (  # noqa: E402
    Arc,
    Circle,
    FancyArrowPatch,
    FancyBboxPatch,
    Wedge,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.resolve().parents[2]  # docs/design/figures -> repository root

INK = "#1a2733"
MUTED = "#5a6b7a"
FAINT = "#8a9aa8"
BORDER = "#c9d2db"
ARM = "#1f6feb"
ROD = "#d64545"
ACTION = "#2e9e5b"
SHAFT = "#24292f"
TILT_DEG = 17.0
SWEEP_DEG = 34.0


def main() -> int:
    """Draw the side elevation and the plan view side by side."""
    sys.path.insert(0, str(ROOT / "src"))
    from furuta.parameters import FurutaParameters

    p = FurutaParameters.from_yaml(ROOT / "config" / "edukit.yaml")
    r, length = p.rotor_arm_length_m, p.pendulum_length_m
    travel_deg = 90.0

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
    fig, (side, plan) = plt.subplots(1, 2, figsize=(11.0, 5.0))

    # =========================================================================
    # Left Panel: Side Elevation (Pendulum tilt)
    # =========================================================================
    side.set_aspect("equal")
    side.axis("off")

    base_y = 0.0
    motor_h = 0.045
    motor_w = 0.055
    hub_y = 0.120

    # Ground plate & hatching
    side.plot([-0.14, 0.14], [base_y, base_y], color=INK, lw=2.2, zorder=2)
    for i in range(11):
        hx = -0.135 + i * 0.026
        side.plot([hx, hx - 0.016], [base_y, base_y - 0.018], color=FAINT, lw=1.2)

    # Stepper motor body
    side.add_patch(
        FancyBboxPatch(
            (-motor_w / 2, base_y),
            motor_w,
            motor_h,
            boxstyle="round,pad=0.002,rounding_size=0.004",
            facecolor="#e2e8f0",
            edgecolor=INK,
            lw=1.6,
            zorder=3,
        )
    )
    side.text(
        0.0,
        base_y + motor_h / 2,
        "stepper\nmotor",
        ha="center",
        va="center",
        fontsize=7.5,
        color=MUTED,
        fontweight="bold",
        zorder=4,
    )

    # Vertical rotor shaft
    side.plot([0.0, 0.0], [base_y + motor_h, hub_y], color=SHAFT, lw=4.0, zorder=2)

    # Rotor Arm (horizontal)
    side.plot(
        [0.0, r], [hub_y, hub_y], color=ARM, lw=5.5, solid_capstyle="round", zorder=3
    )
    side.text(
        r / 2,
        hub_y - 0.024,
        f"rotor arm ({r * 100:.1f} cm)",
        ha="center",
        fontsize=9.0,
        color=ARM,
        fontweight="bold",
        path_effects=[pe.withStroke(linewidth=2.5, foreground="white")],
    )

    # Upright vertical dashed reference line from pivot
    ref_top = hub_y + length * 0.98
    side.plot([r, r], [hub_y, ref_top], color=FAINT, lw=1.2, ls=(0, (4, 3)), zorder=1)
    side.text(
        r - 0.008,
        ref_top + 0.008,
        r"upright ($\theta = 0$)",
        fontsize=8.5,
        color=MUTED,
        ha="right",
        va="bottom",
        fontweight="medium",
    )

    # Pendulum rod
    tilt = math.radians(TILT_DEG)
    tip = (r + length * math.sin(tilt), hub_y + length * math.cos(tilt))
    side.plot(
        [r, tip[0]],
        [hub_y, tip[1]],
        color=ROD,
        lw=4.8,
        solid_capstyle="round",
        zorder=4,
    )
    side.text(
        tip[0] + 0.015,
        tip[1] + 0.005,
        f"pendulum rod ({length * 100:.1f} cm)",
        fontsize=8.8,
        color=ROD,
        fontweight="bold",
        va="bottom",
        ha="left",
    )

    # Pivot bearing at arm tip
    side.add_patch(
        Circle((r, hub_y), 0.011, facecolor="white", edgecolor=INK, lw=1.8, zorder=6)
    )
    side.add_patch(
        Circle((r, hub_y), 0.0035, facecolor=ROD, edgecolor="none", zorder=7)
    )

    # Tilt angle arc
    arc_rad = 0.18
    side.add_patch(
        Arc(
            (r, hub_y),
            arc_rad,
            arc_rad,
            angle=0,
            theta1=90 - TILT_DEG,
            theta2=90,
            color=INK,
            lw=1.5,
            zorder=5,
        )
    )
    side.text(
        r + 0.026,
        hub_y + 0.115,
        r"$\theta$",
        fontsize=15,
        color=INK,
        fontweight="bold",
        path_effects=[pe.withStroke(linewidth=3, foreground="white")],
    )
    side.text(
        r + 0.062,
        hub_y + 0.112,
        "tilt angle",
        fontsize=9.0,
        color=MUTED,
        va="center",
        path_effects=[pe.withStroke(linewidth=2.5, foreground="white")],
    )

    # Angular velocity arrow
    side.add_patch(
        FancyArrowPatch(
            (tip[0] + 0.025, tip[1] - 0.015),
            (tip[0] + 0.052, tip[1] - 0.065),
            connectionstyle="arc3,rad=-0.30",
            arrowstyle="-|>",
            mutation_scale=13,
            color=ROD,
            lw=1.8,
            zorder=5,
        )
    )
    side.text(
        tip[0] + 0.062,
        tip[1] - 0.052,
        r"$\dot{\theta}$",
        fontsize=15,
        color=ROD,
        fontweight="bold",
        path_effects=[pe.withStroke(linewidth=3, foreground="white")],
    )

    side.set_xlim(-0.16, r + length * 0.95)
    side.set_ylim(-0.035, hub_y + length * 1.10)

    # =========================================================================
    # Right Panel: Plan View (Rotor arm sweep)
    # =========================================================================
    plan.set_aspect("equal")
    plan.axis("off")

    # Travel bound sector
    plan.add_patch(
        Wedge(
            (0, 0),
            r * 1.05,
            90 - travel_deg,
            90 + travel_deg,
            facecolor=ARM,
            alpha=0.07,
            lw=0,
            zorder=1,
        )
    )
    # Sector boundary lines
    for sign in (-1, 1):
        a_lim = math.radians(90 + sign * travel_deg)
        plan.plot(
            [0, r * 1.05 * math.cos(a_lim)],
            [0, r * 1.05 * math.sin(a_lim)],
            color=ARM,
            lw=1.3,
            ls=(0, (4, 3)),
            zorder=2,
        )
    plan.text(
        0.0,
        -r * 0.28,
        r"Hard travel limit: $\pm 90^\circ$ ($\pm\pi/2\ \mathrm{rad}$)",
        ha="center",
        fontsize=9.0,
        color=ARM,
        fontweight="bold",
        bbox=dict(
            boxstyle="round,pad=0.2", facecolor="#f0f6ff", edgecolor="#bfdbfe", lw=0.8
        ),
    )

    # Center reference line (phi = 0)
    plan.plot([0, 0], [0, r * 1.15], color=FAINT, lw=1.2, ls=(0, (4, 3)), zorder=1)
    plan.text(
        0.0,
        r * 1.19,
        r"center ($\phi = 0$)",
        fontsize=8.8,
        color=MUTED,
        ha="center",
        fontweight="medium",
    )

    # Rotor arm at SWEEP_DEG
    sw = math.radians(90 - SWEEP_DEG)
    arm_tip = (r * math.cos(sw), r * math.sin(sw))
    plan.plot(
        [0, arm_tip[0]],
        [0, arm_tip[1]],
        color=ARM,
        lw=5.5,
        solid_capstyle="round",
        zorder=3,
    )

    # Central motor shaft hub
    plan.add_patch(Circle((0, 0), 0.010, facecolor=SHAFT, edgecolor="none", zorder=6))

    # Pivot at arm tip
    plan.add_patch(
        Circle(arm_tip, 0.012, facecolor=ROD, edgecolor="white", lw=1.6, zorder=6)
    )
    plan.text(
        arm_tip[0] + 0.016,
        arm_tip[1] + 0.012,
        "pivot",
        fontsize=9.0,
        color=ROD,
        fontweight="bold",
        path_effects=[pe.withStroke(linewidth=2.5, foreground="white")],
    )

    # Sweep angle arc
    arc_sw = 0.70
    plan.add_patch(
        Arc(
            (0, 0),
            r * arc_sw,
            r * arc_sw,
            angle=0,
            theta1=90 - SWEEP_DEG,
            theta2=90,
            color=INK,
            lw=1.5,
            zorder=4,
        )
    )
    # Position phi comfortably inside the arc wedge
    mid_ang = math.radians(90 - SWEEP_DEG / 2)
    plan.text(
        r * 0.42 * math.cos(mid_ang),
        r * 0.42 * math.sin(mid_ang),
        r"$\phi$",
        fontsize=15,
        color=INK,
        fontweight="bold",
        ha="center",
        va="center",
        path_effects=[pe.withStroke(linewidth=3, foreground="white")],
    )

    # Rotor angular rate indicator (outer perimeter)
    plan.add_patch(
        FancyArrowPatch(
            (r * 0.98 * math.cos(sw + 0.18), r * 0.98 * math.sin(sw + 0.18)),
            (r * 0.98 * math.cos(sw - 0.08), r * 0.98 * math.sin(sw - 0.08)),
            connectionstyle="arc3,rad=-0.15",
            arrowstyle="-|>",
            mutation_scale=13,
            color=ARM,
            lw=1.8,
            zorder=5,
        )
    )
    plan.text(
        r * 1.04 * math.cos(sw + 0.06),
        r * 1.04 * math.sin(sw + 0.06),
        r"$\dot{\phi}$",
        fontsize=15,
        color=ARM,
        fontweight="bold",
        va="bottom",
        ha="center",
        path_effects=[pe.withStroke(linewidth=3, foreground="white")],
    )

    # Commanded acceleration action arrow
    plan.add_patch(
        FancyArrowPatch(
            (r * 0.62 * math.cos(sw - 0.22), r * 0.62 * math.sin(sw - 0.22)),
            (r * 0.62 * math.cos(sw - 0.72), r * 0.62 * math.sin(sw - 0.72)),
            connectionstyle="arc3,rad=0.30",
            arrowstyle="-|>",
            mutation_scale=13,
            color=ACTION,
            lw=2.0,
            zorder=5,
        )
    )
    plan.text(
        r * 0.88,
        r * 0.52,
        "Action:\ncommanded acceleration\n"
        + r"$\ddot{\phi}_{\mathrm{cmd}} \in [-11.78, 11.78]\ \mathrm{rad/s^2}$",
        fontsize=8.8,
        color=ACTION,
        fontweight="bold",
        va="center",
        linespacing=1.35,
        bbox=dict(
            boxstyle="round,pad=0.25", facecolor="#f2fbf5", edgecolor="#bbf7d0", lw=0.8
        ),
    )

    plan.set_xlim(-r * 1.30, r * 2.42)
    plan.set_ylim(-r * 0.45, r * 1.35)

    # =========================================================================
    # Bottom Summary Banner (Clean Card)
    # =========================================================================
    fig.text(
        0.5,
        0.032,
        r"$\mathbf{Observation\ vector\ (5D):}\ "
        r"[\cos\theta,\ \sin\theta,\ \dot{\theta},\ \phi,\ \dot{\phi}]$"
        r"       $\mathbf{Action\ (1D):}\ "
        r"a_t \in [-1, 1] \mapsto \ddot{\phi}_{\mathrm{cmd}}$",
        ha="center",
        va="center",
        fontsize=10.0,
        color=INK,
        bbox=dict(
            boxstyle="round,pad=0.4", facecolor="#f8fafc", edgecolor="#e2e8f0", lw=1.2
        ),
    )

    fig.tight_layout()
    fig.subplots_adjust(top=0.90, bottom=0.11)
    fig.text(
        0.012,
        0.975,
        r"Side view: pendulum tilt $\theta$",
        ha="left",
        va="top",
        fontsize=13.0,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.525,
        0.975,
        r"Plan view: rotor arm sweep $\phi$",
        ha="left",
        va="top",
        fontsize=13.0,
        fontweight="bold",
        color=INK,
    )
    out = HERE / "observations.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (arm {r:.4f} m, rod {length:.4f} m, travel ±{travel_deg:.0f}°)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

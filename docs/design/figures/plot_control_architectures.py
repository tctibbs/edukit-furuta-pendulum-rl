# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy"]
# ///
"""Control architecture comparison: cascaded PID versus full-state LQR."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = Path(__file__).resolve().parent

INK = "#1a2733"
MUTED = "#5a6b7a"
BORDER = "#c9d2db"
PID_COLOUR = "#e8833a"
LQR_COLOUR = "#2e9e5b"
SENSOR = "#1f6feb"


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
    title_size: float = 10.0,
    body_size: float = 8.5,
) -> None:
    """Draw a rounded block diagram card."""
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.010,rounding_size=0.015",
            linewidth=1.4,
            edgecolor=edge_color,
            facecolor=bg_color,
            zorder=3,
        )
    )
    if title:
        ax.text(
            x + w / 2,
            y + h - 0.045,
            title,
            ha="center",
            va="top",
            fontsize=title_size,
            color=edge_color,
            fontweight="bold",
            zorder=4,
        )
    if body:
        ax.text(
            x + w / 2,
            y + (h / 2 - 0.015 if not title else h - 0.115),
            body,
            ha="center",
            va="top" if title else "center",
            fontsize=body_size,
            color=INK,
            zorder=4,
            linespacing=1.35,
        )


def draw_arrow(
    ax,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: str,
    label: str = "",
    lw: float = 1.6,
    connectionstyle: str = "arc3,rad=0.0",
    label_offset_y: float = 0.025,
) -> None:
    """Draw a labeled signal flow arrow."""
    ax.add_patch(
        FancyArrowPatch(
            (x0, y0),
            (x1, y1),
            connectionstyle=connectionstyle,
            arrowstyle="-|>",
            mutation_scale=12,
            linewidth=lw,
            color=color,
            zorder=2,
        )
    )
    if label:
        ax.text(
            (x0 + x1) / 2,
            (y0 + y1) / 2 + label_offset_y,
            label,
            ha="center",
            va="center",
            fontsize=8.5,
            color=INK,
            fontweight="medium",
            zorder=5,
            path_effects=[pe.withStroke(linewidth=2.5, foreground="white")],
        )


def main() -> int:
    """Draw the architecture block diagrams."""
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
    fig, ax = plt.subplots(figsize=(10.8, 5.4))
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    ax.axis("off")

    # Outer containers for the two architectures
    # Panel 1: Cascaded PID
    ax.add_patch(
        FancyBboxPatch(
            (0.015, 0.505),
            0.970,
            0.395,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=1.2,
            edgecolor=BORDER,
            facecolor="#fbfcfd",
            zorder=1,
        )
    )
    ax.text(
        0.035,
        0.875,
        "Cascaded PID: two loops joined by a lean reference",
        fontsize=11.5,
        fontweight="bold",
        color=PID_COLOUR,
        va="top",
        zorder=4,
    )
    ax.text(
        0.035,
        0.840,
        "The outer loop turns arm error into a lean reference; the inner loop "
        "balances the pendulum on it.",
        fontsize=9.0,
        color=MUTED,
        va="top",
        zorder=4,
    )

    # Cascaded PID blocks:
    # Arm angle
    draw_box(
        ax,
        0.035,
        0.535,
        0.155,
        0.250,
        "Rotor feedback",
        r"Arm angle $\phi$" "\n" r"$e_\phi = 0 - \phi$",
        SENSOR,
        "#f0f6ff",
    )
    # Outer Loop block
    draw_box(
        ax,
        0.265,
        0.535,
        0.175,
        0.250,
        "Outer loop (PD)",
        r"$u_\phi = K_{p,\phi} e_\phi + K_{d,\phi} \dot{e}_\phi$"
        "\n"
        r"Saturates at $\pm 0.08\text{ rad}$",
        PID_COLOUR,
        "#fff9f5",
    )
    # Inner Loop block
    draw_box(
        ax,
        0.540,
        0.535,
        0.200,
        0.250,
        "Inner loop (PID)",
        r"$e_\theta = \theta_{\mathrm{ref}} - \theta$"
        "\n"
        r"$u = K_{p,\theta} e_\theta + K_i \int e_\theta + K_d \dot{e}_\theta$",
        PID_COLOUR,
        "#fff9f5",
    )
    # Actuator output
    draw_box(
        ax,
        0.815,
        0.535,
        0.150,
        0.250,
        "Actuator demand",
        r"$\ddot{\phi}_{\mathrm{cmd}} \in [-11.8, 11.8]$" "\n" r"$\mathrm{rad/s^2}$",
        INK,
        "#f8fafc",
    )

    # Arrows for PID
    draw_arrow(ax, 0.190, 0.660, 0.265, 0.660, SENSOR, label=r"$e_\phi$")
    draw_arrow(
        ax, 0.440, 0.660, 0.540, 0.660, PID_COLOUR, label=r"$\theta_{\mathrm{ref}}$"
    )
    draw_arrow(ax, 0.740, 0.660, 0.815, 0.660, PID_COLOUR, label=r"$\ddot{\phi}$")
    # Feed pendulum feedback into inner loop
    draw_arrow(
        ax,
        0.640,
        0.505,
        0.640,
        0.535,
        SENSOR,
        label=r"$\theta$ (optical encoder)",
        label_offset_y=-0.035,
    )

    # Panel 2: Full-State LQR
    ax.add_patch(
        FancyBboxPatch(
            (0.015, 0.045),
            0.970,
            0.420,
            boxstyle="round,pad=0.012,rounding_size=0.018",
            linewidth=1.2,
            edgecolor=BORDER,
            facecolor="#fbfcfd",
            zorder=1,
        )
    )
    ax.text(
        0.035,
        0.435,
        "LQR: one gain vector on all four states",
        fontsize=11.5,
        fontweight="bold",
        color=LQR_COLOUR,
        va="top",
        zorder=4,
    )
    ax.text(
        0.035,
        0.400,
        "Pendulum balance and arm recentering come from the same four gains.",
        fontsize=9.0,
        color=MUTED,
        va="top",
        zorder=4,
    )

    # LQR blocks:
    # Full State Vector
    draw_box(
        ax,
        0.035,
        0.080,
        0.240,
        0.270,
        "Full state vector",
        r"$x = [\theta,\; \dot{\theta},\; \phi,\; \dot{\phi}]^T$"
        "\n\n"
        r"$\theta$: pendulum tilt"
        "\n"
        r"$\phi$: rotor displacement",
        SENSOR,
        "#f0f6ff",
    )
    # LQR Gain Matrix Block
    draw_box(
        ax,
        0.380,
        0.080,
        0.340,
        0.270,
        "Gain vector K",
        r"$u = -K x = -K_\theta \theta - K_{\dot{\theta}} \dot{\theta}"
        r" - K_\phi \phi - K_{\dot{\phi}} \dot{\phi}$"
        "\n\n"
        r"Riccati solution: $K = [209.5,\; 28.0,\; -1.0,\; -1.7]$"
        "\n"
        r"Cost weights: $Q = \mathrm{diag}(100, 1, 1, 0.1),\; R = 1$",
        LQR_COLOUR,
        "#f2fbf5",
    )
    # Actuator output
    draw_box(
        ax,
        0.815,
        0.080,
        0.150,
        0.270,
        "Actuator demand",
        r"$\ddot{\phi}_{\mathrm{cmd}} \in [-11.8, 11.8]$" "\n" r"$\mathrm{rad/s^2}$",
        INK,
        "#f8fafc",
    )

    # Arrows for LQR
    draw_arrow(ax, 0.275, 0.215, 0.380, 0.215, SENSOR, label=r"state $x$")
    draw_arrow(ax, 0.720, 0.215, 0.815, 0.215, LQR_COLOUR, label=r"$u = -K x$")

    fig.tight_layout()
    fig.subplots_adjust(top=0.91)
    fig.text(
        0.012,
        0.985,
        "Control architectures: cascaded PID versus state-space LQR",
        ha="left",
        va="top",
        fontsize=13.5,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.012,
        0.930,
        "The cascade joins its two loops through a lean reference; LQR feeds "
        "all four states back through one gain vector.",
        ha="left",
        va="top",
        fontsize=10.2,
        color=MUTED,
    )

    out = HERE / "control_architectures.png"
    fig.savefig(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

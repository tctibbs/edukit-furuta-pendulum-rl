"""Shared style and helpers for the identification figures.

The probe figures are meant to be read by someone new to rotary pendulums. This
module sets the shared style and gives the plot scripts a callout and a footer.
Import it from a figure script. The script adds this directory to its path first.

Nothing plotting-related is imported at module level. The figure runner globs this
directory and runs every file in it. `apply_style` imports matplotlib
when it is called.
"""

from __future__ import annotations

# One palette for the whole battery. Blue is measured data, orange a model, red a
# failure, green a pass.
INK = "#1a2733"  # titles, primary text
MUTED = "#5a6b7a"  # secondary text, ticks
FAINT = "#9aa7b3"  # least-important text
GRID = "#e6ebf0"
MEASURED = "#1f6feb"  # measured, on hardware
MEASURED_FILL = "#cbdefb"  # light blue band for percentile ranges
MODEL = "#e8833a"  # model / analytic prediction
DANGER = "#d64545"  # the simulator's error, or a warning
GOOD = "#2e9e5b"  # confirmed / pass
NEUTRAL = "#8a97a3"


def apply_style() -> None:
    """Set the shared rcParams. Call once at the top of a figure script."""
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Helvetica Neue",
                "Helvetica",
                "Arial",
                "DejaVu Sans",
            ],
            "font.size": 11,
            "axes.titlesize": 14.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 11.5,
            "axes.labelweight": "medium",
            "axes.labelcolor": INK,
            "axes.edgecolor": "#c9d2db",
            "axes.linewidth": 1.0,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.frameon": False,
            "legend.fontsize": 9.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "lines.solid_capstyle": "round",
        }
    )


def titled(ax, title: str, subtitle: str | None = None) -> None:
    """Head a plot so it reads without the write-up beside it."""
    ax.set_title(title, loc="left", color=INK, pad=22 if subtitle else 12)
    if subtitle:
        ax.text(
            0.0,
            1.015,
            subtitle,
            transform=ax.transAxes,
            fontsize=10.5,
            color=MUTED,
            ha="left",
            va="bottom",
        )


def callout(ax, xy, text: str, xytext, color: str = INK) -> None:
    """A boxed note with an arrow to the point it refers to."""
    ax.annotate(
        text,
        xy=xy,
        xytext=xytext,
        fontsize=9.5,
        color=color,
        ha="left",
        va="center",
        arrowprops=dict(
            arrowstyle="-|>",
            color=color,
            lw=1.3,
            connectionstyle="arc3,rad=0.18",
            shrinkA=6,
            shrinkB=4,
        ),
        bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=color, lw=1.1, alpha=0.95),
        zorder=6,
    )


def caption(fig, text: str) -> None:
    """One-sentence footer saying what the figure means."""
    fig.text(0.01, -0.01, text, ha="left", va="top", fontsize=9, color=FAINT, wrap=True)

"""Shared look for Experiment 07's figures: one palette, one set of axes.

A controller keeps one colour wherever it appears. The chrome (ink, grid, rules) is
Experiment 06's `_style.py` unchanged. The five identity hues are checked against each
other in greyscale: the grey, the orange and the purple separate by lightness, and the
blue and the green, which sit close in lightness, never share a row.

The module has no top-level plotting import, so it is safe when the figure runner globs
and runs it directly. It borrows matplotlib from whichever script imports it.
"""

from __future__ import annotations

# --- ink and chrome, Experiment 06's. ---
SURFACE = "#ffffff"
INK = "#1a2733"
MUTED = "#5a6b7a"
GRID = "#e6ebf0"
RULE = "#c9d2db"

# --- one hue per carousel entry. ---
PID = "#6f7d8b"  # the kit's dual PID
LQR = "#e8833a"  # the kit's LQR
CATCH_POLICY = "#1a7f5a"  # BALANCE, a learned balance policy taking the kit's handover
SWINGUP = "#1f6feb"  # SWING-UP, Experiment 06's swing-up policy
JETHRO = "#4a3aa7"  # JETHRO, the gentler swing-up


def apply_style() -> None:
    """Set the shared rcParams. Call once at the top of a figure script."""
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.06,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "font.size": 11,
            "axes.titlesize": 13.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 11,
            "axes.labelcolor": INK,
            "axes.edgecolor": RULE,
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
            "lines.solid_joinstyle": "round",
        }
    )


def save(fig, path, **savefig) -> None:
    """Write the figure and say where it went and how big it is."""
    fig.savefig(path, **savefig)
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")

"""Shared look for the swing-up figures: one palette, one set of axes, one voice.

The five figures here are read one after another in the write-up, so a reader has to
carry meaning between them. That only works if a colour means the same thing on every
page. Blue is the real machine and orange is the simulation. Both come from
experiment 03's `_style.py` unchanged. Red is gone because it previously meant the
bench, the tilt trace, the travel bound, and a missed catch in the same experiment.

The catch map is not identity but a graded outcome, worst to best, so it takes a single
blue ramp with lightness carrying the order. That survives colour blindness and a
greyscale print, which three hues at the same lightness do not.

`tilt_axis` and `arm_axis` set the limits, the ticks, and the threshold marks in one
place, so the tilt panel of a bench capture and the tilt panel of a simulated episode
are the same axis with different data on it.

The module has no top-level plotting import, so it is safe when the figure runner globs
and runs it directly. It borrows matplotlib from whichever script imports it.
"""

from __future__ import annotations

import math

# --- ink and chrome. Shared with experiment 03's figures. ---
SURFACE = "#ffffff"
INK = "#1a2733"  # titles, primary text
MUTED = "#5a6b7a"  # secondary text, ticks, event rules
FAINT = "#9aa7b3"  # thresholds, least-important text
GRID = "#e6ebf0"
RULE = "#c9d2db"  # axis spines
BAND = "#f2f5f8"  # forbidden-region shading

# --- the two hues that carry meaning across every figure. ---
BENCH = "#1f6feb"  # measured on the machine (experiment 03's MEASURED)
SIM = "#e8833a"  # the simulation (experiment 03's MODEL)
# The simulation driven by the bench's own arm motion, dark enough to clear the blue by
# the rule CONTROL follows below. At #a8551a the two converted to greys within ten
# levels of each other however the conversion is done, and the two traces of
# `bench_first_run.png` came out as one trace in a greyscale print. This one converts
# thirty to forty levels below the blue and keeps the orange's hue.
SIM_REPLAY = "#7a3d0f"
# The control run's de-emphasis gray, a darker step of experiment 03's NEUTRAL. It has
# to be darker: at #8a97a3 it and the orange carry the same luminance, so the two are
# one line in a greyscale print even though they are obvious on screen.
CONTROL = "#6f7d8b"
CORRECTED = "#4a3aa7"  # the simulation after ADR-0006 walked the drive target

# --- the catch outcome, an ordered scale rather than three identities. ---
# Blue steps 250 / 500 / 700 of the sequential ramp. Validated as an ordinal ramp
# against a white surface: monotone lightness, every adjacent step clear, light end
# 2.11:1. A clean catch is the near-empty wash; a miss is the ink.
OUTCOME_COLOURS = ("#86b6ef", "#256abf", "#0d366b")
OUTCOME_LABELS = ("clean catch", "fell, swung back up", "miss")
# The middle class takes a texture as well as a step, because it is the one a reader
# could confuse with either neighbour. The ink is a lighter step of the same ramp.
OUTCOME_HATCH = (None, "///", None)
OUTCOME_HATCH_INK = "#9ec5f4"

# --- the axes the time-series figures share. ---
CAPTURE_DEG = 3.0  # the gate's hold window
FALL_DEG = 30.0  # the firmware's fall stop and the catch map's fall threshold
TRAVEL_BOUND_RAD = math.pi  # where an episode terminates on travel
TILT_YLIM = (-9.0, 213.0)  # headroom above 180 for the event labels
TILT_TICKS = (0, 45, 90, 135, 180)
ARM_YLIM = (-3.65, 3.65)
ARM_TICKS = (-math.pi, -math.pi / 2, 0.0, math.pi / 2, math.pi)
ARM_TICK_LABELS = (r"$-\pi$", r"$-\pi/2$", "0", r"$\pi/2$", r"$\pi$")


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
            "legend.fontsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
        }
    )


def titled(
    ax,
    title: str,
    subtitle: str | None = None,
    *,
    pad: float | None = None,
    subtitle_y: float = 1.018,
    fontsize: float | None = None,
    subtitle_size: float = 10.5,
) -> None:
    """Left-aligned bold title with an optional plain-language subtitle under it.

    `pad` and `subtitle_y` open up the band above the axes for the legend row of a panel
    whose data fills it.
    """
    if pad is None:
        pad = 24 if subtitle else 12
    ax.set_title(title, loc="left", color=INK, pad=pad, fontsize=fontsize)
    if subtitle:
        ax.text(
            0.0,
            subtitle_y,
            subtitle,
            transform=ax.transAxes,
            fontsize=subtitle_size,
            color=MUTED,
            ha="left",
            va="bottom",
        )


def figure_titled(fig, title: str, subtitle: str | None = None, y: float = 0.995):
    """The same title block for a figure of several panels, hung off the figure."""
    fig.text(
        0.0, y, title, ha="left", va="top", fontsize=15.5, color=INK, weight="bold"
    )
    if subtitle:
        fig.text(
            0.0,
            y - 0.031,
            subtitle,
            ha="left",
            va="top",
            fontsize=10.8,
            color=MUTED,
        )


def threshold(ax, y: float, label: str, *, x: float = 0.995, ha: str = "right") -> None:
    """A hairline at a threshold, labelled where it sits rather than in the legend.

    A threshold is chrome, not a series: it never takes a hue and never takes a
    legend row.
    """
    ax.axhline(y, color=FAINT, ls=(0, (5, 4)), lw=0.9, zorder=1)
    if label:
        ax.text(
            x,
            y,
            label,
            transform=ax.get_yaxis_transform(),
            ha=ha,
            va="bottom",
            fontsize=9,
            color=FAINT,
        )


def event_rule(ax, x: float) -> None:
    """A vertical rule at a moment the figure names."""
    ax.axvline(x, color=MUTED, lw=1.0, alpha=0.7, zorder=2)


def event_label(ax, x: float, text: str, *, side: str = "left") -> None:
    """Name a moment in the headroom above the data rather than on top of it.

    A tilt trace that swings from 0 to 180 leaves no free space inside the panel, so
    an arrow pointing into it has to cross the curves it is describing. The label goes
    in the band above 180 instead, hard against its own rule.
    """
    ax.text(
        x,
        0.985,
        text + " " if side == "right" else " " + text,
        transform=ax.get_xaxis_transform(),
        ha="left" if side == "right" else "right",
        va="top",
        fontsize=10,
        color=INK,
        zorder=8,
        bbox=dict(boxstyle="round,pad=0.3", fc=SURFACE, ec=GRID, lw=1.0, alpha=0.95),
    )


def readout(
    ax, text: str, *, x: float = 0.985, y: float = 0.5, ha: str = "right"
) -> None:
    """A note in the panel's free space, for what happened outside the window."""
    ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        ha=ha,
        va="center",
        fontsize=10,
        color=MUTED,
        zorder=8,
        linespacing=1.45,
        bbox=dict(boxstyle="round,pad=0.35", fc=SURFACE, ec=GRID, lw=1.0, alpha=0.94),
    )


def tilt_axis(ax, *, fall: bool = False) -> None:
    """The tilt panel, identical in every time-series figure here."""
    ax.set_ylim(*TILT_YLIM)
    ax.set_yticks(list(TILT_TICKS))
    ax.set_ylabel("tilt from vertical (deg)")
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)
    threshold(ax, CAPTURE_DEG, "3 deg, reached vertical", x=0.008, ha="left")
    if fall:
        threshold(ax, FALL_DEG, "30 deg, fallen", x=0.008, ha="left")


def arm_axis(ax) -> None:
    """The arm panel, identical in every time-series figure here."""
    ax.set_ylim(*ARM_YLIM)
    ax.set_yticks(list(ARM_TICKS))
    ax.set_yticklabels(list(ARM_TICK_LABELS))
    ax.set_ylabel("arm angle (rad)")
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)
    ax.axhline(0.0, color=RULE, lw=0.9, zorder=1)
    for sign in (1, -1):
        ax.axhspan(
            sign * TRAVEL_BOUND_RAD,
            sign * ARM_YLIM[1],
            color=BAND,
            lw=0,
            zorder=0,
        )
    ax.text(
        0.008,
        (TRAVEL_BOUND_RAD + ARM_YLIM[1]) / 2,
        "simulated travel bound: the episode ends here",
        transform=ax.get_yaxis_transform(),
        ha="left",
        va="center",
        fontsize=9,
        color=FAINT,
    )


def legend_row(ax, *, loc: str = "upper right", ncol: int = 1) -> None:
    """The legend for two or more series: frameless, on the surface, never a box."""
    ax.legend(
        loc=loc,
        ncol=ncol,
        frameon=True,
        framealpha=0.92,
        edgecolor="none",
        facecolor=SURFACE,
        borderpad=0.5,
        labelspacing=0.55,
        handlelength=2.0,
    )


def save(fig, path, **savefig) -> None:
    """Write the figure and say where it went and how big it is.

    Keywords go straight to `savefig`. `bbox_inches=fig.bbox_inches` is the one that
    gets used: it writes the whole canvas at exactly the figure size, so a figure with
    pinned margins keeps its plot width whatever its labels measure. Passing `None`
    there does the opposite of what it looks like, falling back to the `savefig.bbox`
    rcParam, which `apply_style` sets to the tight crop.
    """
    fig.savefig(path, **savefig)
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")

# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Draw the supplied dual PID controller beside the manual's LQR alternative.

A drawn block diagram rather than a plot of captured data. Laid out from the
architectures in Manual Sec. 9 and Sec. 14. The manual's own figures are not reproduced.

    just figures 03
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

BOX_H = 0.9


def block(ax, x, y, w, label, color=_style.INK):
    """Draw a labelled block centred vertically on `y`."""
    ax.add_patch(
        Rectangle(
            (x, y - BOX_H / 2),
            w,
            BOX_H,
            facecolor="white",
            edgecolor=color,
            linewidth=1.4,
            zorder=3,
        )
    )
    ax.text(
        x + w / 2,
        y,
        label,
        ha="center",
        va="center",
        fontsize=9,
        color=_style.INK,
        zorder=4,
    )
    return x + w


def junction(ax, x, y):
    """Draw a summing junction."""
    ax.add_patch(
        Circle(
            (x, y),
            0.22,
            facecolor="white",
            edgecolor=_style.INK,
            linewidth=1.4,
            zorder=3,
        )
    )
    ax.text(x, y, "+", ha="center", va="center", fontsize=9, color=_style.INK, zorder=4)
    return x + 0.22


def arrow(ax, start, end, color=_style.INK, style="-|>"):
    """Draw a signal arrow between two points."""
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=11,
            color=color,
            linewidth=1.2,
            zorder=2,
        )
    )


def label(ax, x, y, text, color=_style.MUTED, ha="center", va="bottom"):
    """Annotate a signal line."""
    ax.text(x, y, text, ha=ha, va=va, fontsize=8, color=color, zorder=4)


def draw_dual_pid(ax):
    """Draw the supplied firmware, a rotor loop wrapped around a pendulum loop."""
    y = 3.4
    arrow(ax, (0.2, y), (1.18, y))
    label(ax, 0.2, y + 0.2, "rotor command", ha="left")
    junction(ax, 1.4, y)
    arrow(ax, (1.62, y), (2.18, y))
    end = block(ax, 2.2, y, 1.9, "rotor PID", _style.MODEL)
    arrow(ax, (end, y), (end + 0.78, y))
    label(ax, end + 0.39, y + 0.12, "lean")
    junction(ax, end + 1.0, y)
    arrow(ax, (end + 1.22, y), (end + 1.78, y))
    end2 = block(ax, end + 1.8, y, 2.0, "pendulum PID", _style.MEASURED)
    arrow(ax, (end2, y), (end2 + 0.7, y))
    label(ax, end2 + 0.35, y + 0.12, "accel")
    end3 = block(ax, end2 + 0.72, y, 1.9, "rotor and\npendulum")
    arrow(ax, (end3, y), (end3 + 0.7, y))

    inner_y, outer_y = 1.9, 0.9
    for fy, back_x, tag, colour in (
        (inner_y, end + 1.0, "pendulum angle", _style.MEASURED),
        (outer_y, 1.4, "rotor angle", _style.MODEL),
    ):
        ax.plot([end3 + 0.45, end3 + 0.45], [y - 0.45, fy], color=colour, lw=1.2)
        ax.plot([back_x, end3 + 0.45], [fy, fy], color=colour, lw=1.2)
        arrow(ax, (back_x, fy), (back_x, y - 0.25), colour)
        label(ax, (back_x + end3) / 2, fy + 0.1, tag, colour)


def draw_lqr(ax):
    """Draw the manual's alternative, one gain matrix on the whole state."""
    y = 3.4
    arrow(ax, (0.2, y), (1.18, y))
    label(ax, 0.2, y + 0.2, "upright reference", ha="left")
    junction(ax, 1.4, y)
    arrow(ax, (1.62, y), (2.18, y))
    end = block(ax, 2.2, y, 2.6, "gain matrix K", _style.GOOD)
    arrow(ax, (end, y), (end + 0.7, y))
    label(ax, end + 0.35, y + 0.12, "accel")
    end2 = block(ax, end + 0.72, y, 1.9, "rotor and\npendulum")
    arrow(ax, (end2, y), (end2 + 0.7, y))

    fy = 1.4
    ax.plot([end2 + 0.45, end2 + 0.45], [y - 0.45, fy], color=_style.GOOD, lw=1.2)
    ax.plot([1.4, end2 + 0.45], [fy, fy], color=_style.GOOD, lw=1.2)
    arrow(ax, (1.4, fy), (1.4, y - 0.25), _style.GOOD)
    label(
        ax,
        (1.4 + end2) / 2,
        fy + 0.1,
        "all four states: both angles and both rates",
        _style.GOOD,
    )


def main() -> int:
    """Draw both control structures side by side."""
    _style.apply_style()
    fig, (left, right) = plt.subplots(1, 2, figsize=(12.4, 3.6))
    for ax in (left, right):
        ax.set_xlim(0, 11.2)
        ax.set_ylim(0.45, 4.5)
        ax.axis("off")

    draw_dual_pid(left)
    _style.titled(
        left,
        "Supplied firmware: two nested PID loops",
        "Each loop sees one angle. The rotor loop steers by asking the "
        "pendulum to lean.",
    )
    draw_lqr(right)
    _style.titled(
        right,
        "Manual Sec. 14: one regulator",
        "One gain matrix maps the whole state to one command.",
    )

    out = HERE / "control_structures.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

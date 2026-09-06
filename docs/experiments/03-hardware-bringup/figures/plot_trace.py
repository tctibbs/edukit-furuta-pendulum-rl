# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy"]
# ///
"""Plot the golden trace, a swing up from hanging then a hold at the top.

Reads a mode u capture, the stock controller's whole episode. The balance portion logs
at five samples a second against the swing-up's five hundred.

    just figures 03
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

COUNTS_PER_DEGREE = 6.666667
MICROSECONDS_PER_SECOND = 1_000_000.0


def height_above_hanging(counts: int) -> float:
    """0 at hanging, 180 at upright; angles past upright fold back toward 0."""
    deg = abs(counts) / COUNTS_PER_DEGREE
    deg = deg % 360.0
    return 180.0 - abs(deg - 180.0)


def read_continuous(path: Path):
    """Time (s) and height (deg) over the whole episode, with a continuous clock."""
    t, h, states = [], [], []
    offset = 0.0
    last = None
    for line in path.read_text(errors="replace").splitlines():
        fields = line.replace("\r", "").split("\t")
        if len(fields) != 5 or fields[4] not in ("D", "B", "H"):
            continue
        try:
            us = int(fields[1])
            counts = int(fields[2])
        except ValueError:
            continue
        if last is not None and us < last:
            offset += last / MICROSECONDS_PER_SECOND + 0.05
        last = us
        t.append(offset + us / MICROSECONDS_PER_SECOND)
        h.append(height_above_hanging(counts))
        states.append(fields[4])
    return t, h, states


def main() -> int:
    """Plot the measured swing-up-and-hold."""
    source = EXPERIMENT / "trace.tsv"
    if not source.exists():
        raise SystemExit(f"no trace capture at {source}; run probe-trace first")

    t, h, states = read_continuous(source)
    if not t:
        raise SystemExit("no D/B/H samples in the trace capture")
    t0 = t[0]
    t = [x - t0 for x in t]

    _style.apply_style()
    fig, ax = plt.subplots(figsize=(7.8, 4.4))

    # State B is the balance hold.
    bal = [x for x, s in zip(t, states, strict=True) if s == "B"]
    if bal:
        ax.axvspan(min(bal), max(bal), color=_style.MEASURED_FILL, alpha=0.5, lw=0)
        ax.text(
            (min(bal) + max(bal)) / 2,
            96,
            "balancing",
            color=_style.MUTED,
            ha="center",
            fontsize=10.5,
        )
        ax.text(
            min(bal) / 2,
            96,
            "swinging up",
            color=_style.MUTED,
            ha="center",
            fontsize=10.5,
        )

    ax.plot(t, h, color=_style.MEASURED, lw=1.8, label="pendulum (measured)")
    ax.axhline(180, color=_style.GOOD, lw=1.2, ls=":", label="upright (balanced)")
    ax.axhline(0.0, color=_style.GRID, lw=1)

    ax.set_xlabel("time (s)")
    ax.set_ylabel("height above hanging (degrees; 180 = upright)")
    ax.set_ylim(-8, 200)
    ax.set_yticks([0, 45, 90, 135, 180])
    _style.titled(
        ax,
        "Stock Swing-Up and Hold Trace",
        "The reference episode the simulation has to reproduce.",
    )
    ax.legend(loc="lower right", fontsize=9)

    fig.tight_layout()
    out = HERE / "trace_swingup.png"
    fig.savefig(out)
    hold = (max(bal) - min(bal)) if bal else 0.0
    print(f"wrote {out}  (peak {max(h):.0f} deg, balance hold {hold:.1f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

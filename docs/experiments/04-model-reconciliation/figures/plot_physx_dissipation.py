# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "pyyaml"]
# ///
"""Effective quality factor Q against swing size, both simulations over hardware.

The same hardware and the same equation ladders as `plot_dissipation.py`, with the
PhysX ladders added. Those are CSVs the GPU host produced from the same ring-down
ladder. This is the figure the tier comparison in `../writeup.md` reads from: colour
carries the condition and marker shape carries where the ladder ran, so the two curves
of a condition lying on each other is the result.

The PhysX ladders stop at a lower swing size than the equation ones because the host
capture walked a shorter ladder. Each rms printed below covers the bins that curve
shares with hardware, so they compare within a curve and not across curves of
different reach.

    just figures 04
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.legend_handler import HandlerTuple  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _datasets as D  # noqa: E402
import _reconcile as R  # noqa: E402
import _style  # noqa: E402

# Both simulations share a label, so the legend carries one row per condition.
VISCOUS = "viscous only, both simulations"
RECONCILED = "reconciled, both simulations"

REQUIRED = ("qeff_before.csv", "qeff_after.csv")


def main() -> int:
    """Overlay the PhysX ladders on the equation ladders and the measured decays."""
    missing = [name for name in REQUIRED if not D.available(name)]
    if missing:
        print(f"skipped: {', '.join(missing)} not present (produced on the GPU host)")
        return 0

    hardware = D.qeff("qeff_hardware.csv")
    curves = [
        (R.sim_qeff(0.0, 0.0), _style.DANGER, (0, (5, 2)), "o", VISCOUS),
        (
            R.sim_qeff(R.AFTER_COULOMB_DEG, R.AFTER_DRAG),
            _style.MODEL,
            "-",
            "o",
            RECONCILED,
        ),
        (D.qeff("qeff_before.csv"), _style.DANGER, (0, (1, 2)), "s", VISCOUS),
        (
            D.qeff("qeff_after.csv"),
            _style.MODEL,
            (0, (4, 1.5, 1, 1.5)),
            "s",
            RECONCILED,
        ),
    ]

    _style.apply_style()
    fig, ax = plt.subplots(figsize=(7.8, 4.9))
    hx, hy = _style.hardware_backdrop(ax, hardware)

    drawn: dict[str, list] = {}
    for pairs, colour, dashes, marker, label in curves:
        x, y = D.binned_median(pairs)
        (line,) = ax.plot(
            x,
            y,
            color=colour,
            lw=2.2,
            ls=dashes,
            marker=marker,
            markersize=4,
            markerfacecolor="white" if marker == "o" else colour,
            markeredgewidth=1.4,
        )
        drawn.setdefault(label, []).append(line)

    ax.set_xlabel("swing size (degrees from hanging)")
    ax.set_ylabel("Q, how slowly energy is lost")
    ax.set_ylim(0, 34)
    ax.set_xlim(0, 175)
    _style.titled(
        ax,
        "Q vs Swing Size in PhysX",
        "Round markers are the equation, squares PhysX.",
    )
    handles, labels = ax.get_legend_handles_labels()
    for label in (VISCOUS, RECONCILED):
        handles.append(tuple(drawn[label]))
        labels.append(label)
    ax.legend(
        handles,
        labels,
        loc="upper right",
        fontsize=9,
        handlelength=3.4,
        handler_map={tuple: HandlerTuple(ndivide=None, pad=0.0)},
    )

    fig.tight_layout()
    out = HERE / "dissipation_physx.png"
    fig.savefig(out)

    # One rms per curve, each over the bins it shares with hardware, plus the worst gap
    # between the two simulations in a condition. The write-up quotes all of these.
    hwd = dict(zip(hx, hy, strict=True))
    report = []
    binned = []
    for i, (pairs, _colour, _dashes, _marker, label) in enumerate(curves):
        cx, cy = D.binned_median(pairs)
        curve = dict(zip(cx, cy, strict=True))
        binned.append(curve)
        shared = [c for c in hwd if c in curve]
        rms = float(np.sqrt(np.mean([(curve[c] - hwd[c]) ** 2 for c in shared])))
        where = "equation" if i < 2 else "PhysX"
        report.append(f"{label.split(',')[0]} {where} {rms:.2f} over {len(shared)}")
    for name, eq, px in (("viscous only", 0, 2), ("reconciled", 1, 3)):
        both = set(binned[eq]) & set(binned[px])
        worst = max(abs(binned[eq][c] - binned[px][c]) for c in both)
        report.append(f"{name} PhysX vs equation worst {worst:.2f} over {len(both)}")
    print(f"wrote {out}  ({'; '.join(report)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

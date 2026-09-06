# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "pyyaml"]
# ///
"""Effective quality factor Q against swing size, the equation over hardware.

The measured decays are `qeff_hardware.csv`. Both ladders come from
`_reconcile.sim_qeff`, run here, before and after the loss terms this experiment
fitted. What each term does to the shape is in `../writeup.md`.

This figure carries one simulation on purpose. `plot_physx_dissipation.py` adds the
PhysX ladders, in the section that introduces them.

    just figures 04
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _datasets as D  # noqa: E402
import _reconcile as R  # noqa: E402
import _style  # noqa: E402


def main() -> int:
    """Draw the viscous-only and reconciled equation ladders over hardware."""
    hardware = D.qeff("qeff_hardware.csv")
    curves = [
        (R.sim_qeff(0.0, 0.0), _style.DANGER, (0, (5, 2)), "viscous only"),
        (
            R.sim_qeff(R.AFTER_COULOMB_DEG, R.AFTER_DRAG),
            _style.MODEL,
            "-",
            "reconciled: + Coulomb + drag",
        ),
    ]

    _style.apply_style()
    fig, ax = plt.subplots(figsize=(7.8, 4.9))
    hx, hy = _style.hardware_backdrop(ax, hardware)

    for pairs, colour, dashes, label in curves:
        x, y = D.binned_median(pairs)
        ax.plot(
            x,
            y,
            color=colour,
            lw=2.3,
            ls=dashes,
            marker="o",
            markersize=4,
            markerfacecolor="white",
            markeredgewidth=1.4,
            label=label,
        )

    ax.set_xlabel("swing size (degrees from hanging)")
    ax.set_ylabel("Q, how slowly energy is lost")
    ax.set_ylim(0, 34)
    ax.set_xlim(0, 175)
    _style.titled(
        ax,
        "Q vs Swing Size",
        "Higher Q means less loss per cycle.",
    )
    ax.legend(loc="upper right", fontsize=9)

    _style.callout(
        ax,
        (hx[-1], hy[-1]),
        "Viscous damping alone runs 5 Q high through the middle\nof the range and much "
        "higher at small swings. The fitted\nCoulomb bite and drag bring it onto the "
        "measurement.",
        (16, 4.6),
        color=_style.INK,
    )

    fig.tight_layout()
    out = HERE / "dissipation_reconciled.png"
    fig.savefig(out)

    hwd = dict(zip(hx, hy, strict=True))
    report = []
    for pairs, _colour, _dashes, label in curves:
        cx, cy = D.binned_median(pairs)
        curve = dict(zip(cx, cy, strict=True))
        shared = [c for c in hwd if c in curve]
        rms = float(np.sqrt(np.mean([(curve[c] - hwd[c]) ** 2 for c in shared])))
        report.append(f"{label.split(':')[0]} {rms:.2f} over {len(shared)}")
    print(f"wrote {out}  (rms vs hardware: {'; '.join(report)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

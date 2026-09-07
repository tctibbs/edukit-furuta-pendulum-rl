# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Draw action saturation and the learned noise std across the successful run.

Run 4 cut `init_noise_std` to stop actions clipping at the rails, and learning got
worse. This is why: through the whole of run 5, which reached the episode cap, the
learned std stays near 1.0 and roughly 40 percent of sampled actions clip, and the
policy succeeds anyway. The clipping is a property of how this plant has to be explored.

    just figures 04
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

EXPERIMENT = HERE.parent


def main() -> int:
    """Draw the twin-axis plot and write it beside this script."""
    ledger = EXPERIMENT / "results.csv"
    if not ledger.exists():
        raise SystemExit(
            f"{ledger} is missing; it is parsed from the training run log."
        )

    iters, sat, std = [], [], []
    with ledger.open() as fh:
        for row in csv.DictReader(fh):
            if not row["saturated_fraction"] or not row["noise_std"]:
                continue
            iters.append(int(row["iteration"]))
            sat.append(float(row["saturated_fraction"]))
            std.append(float(row["noise_std"]))

    # Stacked and sharing an x axis, not twin y axes. Two curves on one frame with
    # different units and no legend is the shape that made the first version unreadable.
    _style.apply_style()
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(7.5, 4.4), sharex=True, height_ratios=[1, 1]
    )

    top.plot(iters, sat, color="#d62728", linewidth=1.4)
    top.set_ylabel("actions clipped\nat a rail")
    top.set_ylim(0, 0.7)
    top.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    top.spines[["top", "right"]].set_visible(False)

    bottom.plot(iters, std, color="#1f77b4", linewidth=1.4)
    bottom.set_ylabel("learned action\nnoise std")
    bottom.set_ylim(0, 1.5)
    bottom.set_xlabel("training iteration")
    bottom.spines[["top", "right"]].set_visible(False)

    # tight_layout has to run first: figure_titled makes room for the heading with
    # subplots_adjust, and a later tight_layout discards it and draws over the panels.
    fig.tight_layout()
    _style.figure_titled(
        fig,
        "Clipping and Exploration Noise",
        "Both stay high through the run that learned.",
    )
    out = HERE / "saturation.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")
    print(f"  saturation range {min(sat):.3f} to {max(sat):.3f}")
    print(f"  noise std range  {min(std):.3f} to {max(std):.3f}")
    return 0


if __name__ == "__main__":
    main()

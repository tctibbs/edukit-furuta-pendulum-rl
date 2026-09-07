# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Draw the disturbance-recovery curve from the evaluation sweeps.

Reads `recovery.csv` beside this experiment, one row per (seed, kick magnitude), and
draws recovery rate against kick size. The x axis ends at 1.0 rad/s because 1.011 rad/s
is the entire recoverable velocity window at upright, so the sweep spans nothing to
everything by construction.

    just figures 04
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

EXPERIMENT = HERE.parent
RECOVERABLE_WINDOW = 1.011


def main() -> int:
    """Draw the curve and write it beside this script."""
    ledger = EXPERIMENT / "recovery.csv"
    if not ledger.exists():
        raise SystemExit(
            f"{ledger} is missing. It is merged from the per-seed evaluation CSVs the "
            "training host writes to results/eval_seed<N>.csv; see logbook.md."
        )

    by_seed: dict[str, list[tuple[float, float]]] = defaultdict(list)
    with ledger.open() as fh:
        for row in csv.DictReader(fh):
            if row["recovery_rate"] in ("", "nan"):
                continue
            by_seed[row["seed"]].append(
                (float(row["kick_rad_s"]), float(row["recovery_rate"]))
            )

    _style.apply_style()

    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    for seed, points in sorted(by_seed.items()):
        points.sort()
        xs, ys = zip(*points, strict=True)
        wide = len(points) > 6  # seed 1 carries the fine grid
        ax.plot(
            xs,
            ys,
            marker="o",
            markersize=3.5,
            linewidth=1.8 if wide else 1.0,
            alpha=1.0 if wide else 0.55,
            label=f"seed {seed}" + (" (fine grid)" if wide else ""),
        )

    ax.axvline(
        RECOVERABLE_WINDOW,
        color="#888888",
        linestyle="--",
        linewidth=1.0,
        label=f"recoverable window, {RECOVERABLE_WINDOW} rad/s",
    )
    ax.set_xlabel("kick magnitude (rad/s)")
    ax.set_ylabel("recovery rate")
    ax.set_ylim(-0.02, 1.02)
    ax.legend(loc="lower left", frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    _style.titled(
        ax,
        "Recovery Rate vs Kick Size",
        "How hard a disturbance the policy still catches.",
    )
    fig.tight_layout()
    out = HERE / "recovery_curve.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    main()

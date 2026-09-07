# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Draw the balance training curve from the parsed run log.

Reads `results.csv` beside this experiment, which carries one row per training
iteration, and draws episode length against iteration. Episode length is the success
number for a balance task: the policy is trying to survive, and the reward it collects
is mostly a function of how long it manages to. When `results_momentum.csv` is
present, the follow-on task's seed 1 curve is drawn beside it: same trainer, same
reward, episodes started across the recoverable set instead of near rest.

    just figures 05
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
EPISODE_STEPS = 5000
STEP_DT = 0.002


def load(path: Path) -> dict[str, list[float]]:
    """Read the results ledger into columns."""
    rows: dict[str, list[float]] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            for key, value in row.items():
                rows.setdefault(key, []).append(float(value))
    return rows


def main() -> int:
    """Draw the curve and write it beside this script."""
    data = load(EXPERIMENT / "results.csv")
    _style.apply_style()
    fig, ax = plt.subplots(figsize=(7.5, 4.0))

    seconds = [v * STEP_DT for v in data["episode_length"]]
    ax.plot(
        data["iteration"],
        seconds,
        color="#1f77b4",
        linewidth=1.6,
        label="balance, near-rest starts, seed 1",
    )
    momentum = EXPERIMENT / "results_momentum.csv"
    if momentum.exists():
        follow = load(momentum)
        ax.plot(
            follow["iteration"],
            [v * STEP_DT for v in follow["episode_length"]],
            color="#d55e00",
            linewidth=1.6,
            label="balance, starts across the recoverable set, seed 1",
        )
    ax.axhline(
        EPISODE_STEPS * STEP_DT,
        color="#888888",
        linestyle="--",
        linewidth=1.0,
        label=f"training episode cap, {EPISODE_STEPS * STEP_DT:.0f} s",
    )
    ax.set_xlabel("training iteration")
    ax.set_ylabel("mean episode length (s)")
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.92), frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    _style.titled(
        ax,
        "Episode Length vs Training Iteration",
        "Longer is better. The training cap is 10 seconds.",
    )
    fig.tight_layout()
    out = HERE / "learning_curve.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    main()

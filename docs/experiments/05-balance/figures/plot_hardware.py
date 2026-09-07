# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy"]
# ///
"""What the policy did on the real machine, from the board's own logs.

Reads the two captures beside this experiment, both written by the firmware's mode `b`
(`docs/runbooks/edukit-firmware.md`) and streamed to disk by `just hw-rl-balance`:
`hardware_rl_balance.tsv`, the first catch, and `hardware_rl_balance_series.tsv`, five
consecutive attempts. Each capture holds the swing-up at 77 Hz as `D` lines, then the
board's per-cycle log of the hold at 500 Hz as `R` lines, dumped from RAM after the run
because a serial line per cycle starves the 500 Hz loop.

Three panels: one attempt end to end, every attempt's first two seconds after the
handover, and what separated the catches from the losses.

    just figures 05
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _style  # noqa: E402

EXPERIMENT = HERE.parent
RAD_PER_COUNT = 2.0 * math.pi / 2400.0
RAD_PER_MICROSTEP = 2.0 * math.pi / 3200.0
# The command is logged in microsteps per second squared, the unit the drive takes.
RAD_S2_PER_UNIT = RAD_PER_MICROSTEP
UPRIGHT_COUNTS = 1200
HOLD_DEG = 3.0
# The action scale the deployed policy trained with; the command rails there.
BOUND_RAD_S2 = 40.0


def read_capture(path: Path) -> list[dict]:
    """Split a capture into attempts, each with its swing-up and its hold."""
    attempts: list[dict] = []
    current: dict | None = None
    swing: list[tuple[float, int]] = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip("\r")
        if line.endswith("\tD"):
            parts = line.split("\t")
            # The board restarts its clock for each swing-up.
            if swing and int(parts[1]) < swing[-1][0] * 1e6:
                swing = []
            swing.append((int(parts[1]) / 1e6, int(parts[2])))
        elif line.startswith("RL HANDOVER"):
            if current is not None:
                attempts.append(current)
            current = {
                "arrival": float(line.split("seeded ")[1].split(" ")[0]) / 1000.0,
                "swing": swing,
                "hold": [],
                "ms": 0,
            }
            swing = []
        elif line.startswith("RL STOP") and current is not None:
            current["ms"] = int(line.split("(")[1].split(" ms")[0])
        elif line.endswith("\tR") and current is not None:
            parts = line.split("\t")
            current["hold"].append(
                (int(parts[1]) / 1e6, int(parts[2]), int(parts[3]), int(parts[4]))
            )
    if current is not None:
        attempts.append(current)
    return [a for a in attempts if a["hold"]]


def hold_arrays(attempt: dict):
    """Time, tilt in degrees, arm angle in radians, command in rad/s^2."""
    hold = np.array(attempt["hold"], dtype=float)
    tilt = np.degrees((hold[:, 1] - UPRIGHT_COUNTS) * RAD_PER_COUNT)
    return (
        hold[:, 0],
        tilt,
        hold[:, 2] * RAD_PER_MICROSTEP,
        hold[:, 3] * RAD_S2_PER_UNIT,
    )


def main() -> int:
    """Draw the three panels and write the figure beside this script."""
    single = EXPERIMENT / "hardware_rl_balance.tsv"
    series = EXPERIMENT / "hardware_rl_balance_series.tsv"
    for needed in (single, series):
        if not needed.exists():
            raise SystemExit(
                f"{needed} is missing. Both come off the board with "
                "`just hw-rl-balance`; see logbook.md."
            )
    attempts = read_capture(series)
    best = max(attempts, key=lambda a: a["ms"])

    _style.apply_style()

    fig = plt.figure(figsize=(7.5, 8.2))
    grid = fig.add_gridspec(3, 1, height_ratios=[1.0, 1.0, 0.9], hspace=0.42)
    top, middle, bottom = (fig.add_subplot(grid[i, 0]) for i in range(3))

    # The best attempt, end to end: the swing-up in the machine's own angle from
    # hanging, then the hold, on one clock.
    swing = np.array(best["swing"], dtype=float)
    handover_t = swing[-1, 0]
    top.plot(
        swing[:, 0],
        np.degrees(swing[:, 1] * RAD_PER_COUNT),
        color="#0072b2",
        linewidth=1.1,
        label="swing-up, the stock firmware",
    )
    t, tilt, _, _ = hold_arrays(best)
    top.plot(
        handover_t + t,
        180.0 + tilt,
        color="#009e73",
        linewidth=1.1,
        label="hold, the trained policy",
    )
    top.axvline(handover_t, color="#888888", linestyle=":", linewidth=1.0)
    top.axhline(180.0, color="#bbbbbb", linewidth=0.6)
    top.set_xlabel("time from the start of the swing-up (s)")
    top.set_ylabel("angle from hanging (deg)")
    top.set_title(
        f"One attempt: {len(best['swing'])} logged samples of swing-up, "
        f"then {best['ms'] / 1000:.1f} s of balance",
        fontsize=9,
    )
    top.legend(loc="upper left", frameon=False, fontsize=8)
    top.spines[["top", "right"]].set_visible(False)

    # Every attempt's first two seconds after the handover.
    middle.axhspan(-HOLD_DEG, HOLD_DEG, color="#dddddd", alpha=0.6, lw=0)
    for attempt in attempts:
        t, tilt, _, _ = hold_arrays(attempt)
        keep = t <= 2.0
        held = attempt["ms"] > 2000
        middle.plot(
            t[keep],
            tilt[keep],
            color="#009e73" if held else "#d55e00",
            linewidth=1.4 if held else 1.0,
            alpha=1.0 if held else 0.8,
            label=f"{attempt['arrival']:+.2f} rad/s, "
            + (f"held {attempt['ms'] / 1000:.0f} s" if held else "lost"),
        )
    middle.set_xlabel("time from the handover (s)")
    middle.set_ylabel("tilt from upright (deg)")
    middle.set_title(
        "Every attempt, by the pendulum's rate as the firmware handed it over",
        fontsize=9,
    )
    middle.legend(loc="upper left", frameon=False, fontsize=7, ncol=2)
    middle.spines[["top", "right"]].set_visible(False)

    # What the policy asked the drive for, over the same window. Five attempts are too
    # few for the arrival rate or the time on the rail to separate a catch from a loss,
    # and neither does; what they do show is how close to the bound every attempt runs.
    bottom.axhspan(-BOUND_RAD_S2, BOUND_RAD_S2, color="#f2f2f2", lw=0)
    for level in (-BOUND_RAD_S2, BOUND_RAD_S2):
        bottom.axhline(level, color="#888888", linestyle="--", linewidth=1.0)
    for attempt in attempts:
        t, _, _, command = hold_arrays(attempt)
        keep = t <= 0.5
        held = attempt["ms"] > 2000
        bottom.plot(
            t[keep],
            command[keep],
            color="#009e73" if held else "#d55e00",
            linewidth=1.2 if held else 0.9,
            alpha=1.0 if held else 0.8,
        )
    bottom.set_xlabel("time from the handover (s)")
    bottom.set_ylabel("commanded rotor\nacceleration (rad/s^2)")
    bottom.set_ylim(-BOUND_RAD_S2 * 1.25, BOUND_RAD_S2 * 1.25)
    bottom.set_title(
        f"What the policy asked for, against its {BOUND_RAD_S2:.0f} rad/s^2 bound "
        "(dashed). Held in green, lost in orange",
        fontsize=9,
    )
    bottom.spines[["top", "right"]].set_visible(False)

    out = HERE / "hardware_balance.png"
    _style.figure_titled(
        fig,
        "On the Machine",
        "Five consecutive attempts at the stock firmware's own swing-up.",
    )
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")
    for attempt in attempts:
        _, tilt, arm, command = hold_arrays(attempt)
        print(
            f"  arrival {attempt['arrival']:+.2f} rad/s, "
            f"{attempt['ms'] / 1000:5.1f} s, "
            f"tilt rms {np.sqrt((tilt**2).mean()):.2f} deg, arm span "
            f"{arm.max() - arm.min():.2f} rad, railed "
            f"{100 * np.mean(np.abs(command) >= BOUND_RAD_S2 - 0.1):.0f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

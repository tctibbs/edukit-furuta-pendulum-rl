# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Hand the simulator the rotor motion the real machine made and watch the pendulum.

Replaying the hardware's reference swing-up capture drives the simulated rotor along the
trajectory the real rotor took and leaves the pendulum free. A divergence is then the
plant model rather than a controller reacting differently.

The upper panel overlays the planar and PhysX replays on the measured pendulum angle.
What the capture leaves open is in `../writeup.md`.

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
import _datasets as D  # noqa: E402
import _style  # noqa: E402

REQUIRED = (
    "replay_planar.csv",
    "replay_before.csv",
    "replay_after.csv",
    "replay_after_bangbang.csv",
    "trace_rotor.csv",
    "trace_dropouts.csv",
)


def dropouts() -> list[tuple[float, float]]:
    """Windows where the capture logged nothing, in seconds."""
    with (D.DATA / "trace_dropouts.csv").open() as handle:
        return [
            (float(row["start_s"]), float(row["end_s"]))
            for row in csv.DictReader(handle)
        ]


def apex(times: list[float], tilt: list[float]) -> list[tuple[float, float]]:
    """Top of each swing: the local minima of distance from upright."""
    out: list[tuple[float, float]] = []
    for i in range(2, len(tilt) - 2):
        here = abs(tilt[i])
        rising = here <= abs(tilt[i - 1]) and here < abs(tilt[i + 1])
        if rising and here < 170.0 and (not out or times[i] - out[-1][0] > 0.25):
            out.append((times[i], here))
    return out


def main() -> int:
    """Overlay the measured climb with the planar and PhysX predictions."""
    missing = [name for name in REQUIRED if not D.available(name)]
    if missing:
        print(f"skipped: {', '.join(missing)} not present (produced on the GPU host)")
        return 0

    planar = D.replay("replay_planar.csv")
    before = D.replay("replay_before.csv")
    after = D.replay("replay_after.csv")
    bang = D.replay("replay_after_bangbang.csv")
    rotor = D.replay("trace_rotor.csv")
    windows = dropouts()

    _style.apply_style()
    fig, (ax, ax_rotor) = plt.subplots(
        2, 1, figsize=(8.6, 6.4), height_ratios=[3, 1.15], sharex=True
    )

    for start, end in windows:
        for panel in (ax, ax_rotor):
            panel.axvspan(start, end, color=_style.DANGER, alpha=0.07, lw=0, zorder=0)

    ax.plot(
        planar["t_s"],
        [abs(v) for v in planar["planar_tilt_deg"]],
        color=_style.NEUTRAL,
        lw=1.6,
        ls=(0, (1, 2)),
        label="equation only",
    )
    ax.plot(
        before["t_s"],
        [abs(v) for v in before["sim_tilt_deg"]],
        color=_style.DANGER,
        lw=1.7,
        ls=(0, (5, 2)),
        alpha=0.85,
        label="PhysX before",
    )
    ax.plot(
        after["t_s"],
        [abs(v) for v in after["sim_tilt_deg"]],
        color=_style.MODEL,
        lw=2.1,
        label="PhysX after, straight line in gaps",
    )
    ax.plot(
        bang["t_s"],
        [abs(v) for v in bang["sim_tilt_deg"]],
        color=_style.GOOD,
        lw=2.1,
        label="PhysX after, accelerate then brake",
    )
    ax.plot(
        after["t_s"],
        [abs(v) for v in after["measured_tilt_deg"]],
        color=_style.MEASURED,
        lw=2.5,
        label="measured",
    )

    ax.set_ylabel("distance from upright (degrees)")
    ax.set_ylim(-8, 190)
    ax.invert_yaxis()
    ax.axhline(0.0, color=_style.GOOD, lw=1.0, ls=(0, (4, 3)))
    ax.text(7.75, 5.0, "upright", color=_style.GOOD, fontsize=9, va="top", ha="right")
    _style.titled(
        ax,
        "Replayed Climb vs Measured",
        "Lower is closer to upright. Orange and green differ only in the gaps.",
    )
    # No curve enters the upper left until the very end of the climb.
    legend = ax.legend(loc="upper left", ncol=2, fontsize=8.4, framealpha=0.94)
    legend.set_frame_on(True)
    legend.get_frame().set_edgecolor(_style.GRID)
    legend.get_frame().set_facecolor("white")
    # Markers only. A line between these points would come from the interpolator rather
    # than from the capture.
    ax_rotor.plot(
        rotor["t_s"],
        rotor["rotor_deg"],
        marker="o",
        markersize=2.6,
        linestyle="none",
        color=_style.INK,
    )
    ax_rotor.set_ylabel("rotor (deg)")
    ax_rotor.set_xlabel("time (seconds)")
    ax_rotor.set_ylim(8, 56)
    ax_rotor.text(
        0.01,
        0.97,
        "Two logged values. All 16 transitions fall inside the shaded gaps.",
        transform=ax_rotor.transAxes,
        fontsize=9,
        color=_style.MUTED,
        va="top",
    )

    fig.tight_layout()
    out = HERE / "trace_replay.png"
    fig.savefig(out)

    print(
        f"wrote {out}  (closest to upright: hardware "
        f"{min(abs(v) for v in after['measured_tilt_deg']):.1f}, "
        f"reconciled/linear {min(abs(v) for v in after['sim_tilt_deg']):.1f}, "
        f"reconciled/bangbang {min(abs(v) for v in bang['sim_tilt_deg']):.1f}, "
        f"before {min(abs(v) for v in before['sim_tilt_deg']):.1f}, "
        f"planar {min(abs(v) for v in planar['planar_tilt_deg']):.1f} deg; "
        f"{len(windows)} dropouts)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

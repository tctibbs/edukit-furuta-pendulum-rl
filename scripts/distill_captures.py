# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pyyaml"]
# ///
"""Turn experiment 03's bench captures into the small datasets experiment 04 plots.

The raw captures are 5 MB of 500 Hz samples and are not committed. The figures plot a
few hundred derived rows of that, written out beside the write-up and small enough to
commit. Redrawing a figure needs no bench and no GPU.

Run it after taking a fresh capture, and commit what changes:

    uv run scripts/distill_captures.py
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from furuta.planar import PlanarModel  # noqa: E402
from furuta.pump import (  # noqa: E402
    qeff_vs_amplitude,
    read_state_trace,
    split_segments,
)
from furuta.trace import read_trace, replay  # noqa: E402

COUNTS_PER_DEGREE = 6.666667
GAP_S = 0.030

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--captures",
    type=Path,
    default=REPO / "docs" / "experiments" / "03-hardware-bringup",
    help="folder holding pump.tsv, sweep.tsv and trace.tsv",
)
parser.add_argument(
    "--out",
    type=Path,
    default=REPO / "docs" / "experiments" / "04-model-reconciliation",
    help="folder to write the distilled datasets into",
)
args = parser.parse_args()


def write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    """Write one dataset and report its row count."""
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {path.name:<24} {len(rows):5d} rows")


def dissipation(captures: Path, out: Path) -> None:
    """Effective Q against amplitude, one row per fitted half decay."""
    trace, states = read_state_trace(captures / "pump.tsv", COUNTS_PER_DEGREE)
    rows = []
    for segment in split_segments(trace, states):
        for amplitude, quality in qeff_vs_amplitude(segment):
            # The same window the figures plot. Outside it the fit is reading encoder
            # dither at the bottom or a partial first swing at the top.
            if 3.0 < amplitude < 175.0 and 0.0 < quality < 60.0:
                rows.append(
                    [
                        round(segment.target_amplitude_deg, 1),
                        round(amplitude, 4),
                        round(quality, 4),
                    ]
                )
    write(out / "qeff_hardware.csv", ["release_deg", "amplitude_deg", "quality"], rows)


def golden(captures: Path, out: Path) -> None:
    """Reference climb: prediction against measurement, the rotor log and its gaps."""
    run = read_trace(captures / "trace.tsv")[0]

    predicted = replay(run, PlanarModel.from_parameters())
    write(
        out / "replay_planar.csv",
        ["t_s", "measured_tilt_deg", "planar_tilt_deg"],
        [
            [round(t, 4), round(math.degrees(m), 4), round(math.degrees(p), 4)]
            for t, m, p in zip(run.time_s, run.tilt_rad, predicted, strict=True)
        ],
    )

    rotor_deg = [math.degrees(a) for a in run.rotor_rad]
    write(
        out / "trace_rotor.csv",
        ["t_s", "rotor_deg"],
        [
            [round(t, 4), round(a, 4)]
            for t, a in zip(run.time_s, rotor_deg, strict=True)
        ],
    )

    # The windows the firmware logged nothing through.
    gaps = []
    for i in range(len(run.time_s) - 1):
        if run.time_s[i + 1] - run.time_s[i] > GAP_S:
            gaps.append(
                [
                    round(run.time_s[i], 4),
                    round(run.time_s[i + 1], 4),
                    round(rotor_deg[i], 4),
                    round(rotor_deg[i + 1], 4),
                ]
            )
    write(
        out / "trace_dropouts.csv",
        ["start_s", "end_s", "rotor_start_deg", "rotor_end_deg"],
        gaps,
    )
    travel = sum(abs(b - a) for a, b in zip(rotor_deg, rotor_deg[1:], strict=False))
    in_gaps = sum(abs(g[3] - g[2]) for g in gaps)
    share = 100.0 * in_gaps / travel if travel else 0.0
    print(
        f"  rotor travel inside the dropouts: {share:.0f} percent of {travel:.0f} deg"
    )


def main() -> int:
    """Write every distilled dataset."""
    missing = [
        name
        for name in ("pump.tsv", "sweep.tsv", "trace.tsv")
        if not (args.captures / name).exists()
    ]
    if missing:
        print(f"[fail ] {args.captures} is missing {', '.join(missing)}")
        print("        these are bench captures; the hw-probe-* recipes take them")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"[info ] {args.captures} -> {args.out}")
    dissipation(args.captures, args.out)
    golden(args.captures, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

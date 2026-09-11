# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""The first two bench sessions, each against what the simulation said would happen.

Reads the raw mode `r` captures beside this experiment, one row per 2 ms control cycle
for the first three seconds of an attempt and one per 50 ms for the rest of the thirty,
carrying the pendulum's encoder counts from hanging and the arm's dead-reckoned
microsteps. The board has no arm encoder, so that dead reckoning is the only arm angle
there is, and the arm panel's axis label says so. The dense window is what is drawn; the
decimated tail from `HOLD_FROM_S` onward is where the hold figures in the panel notes
come from, and the note names the window it used.

Both figures are the same two panels on the same axes as the simulated episode in
`plot_swingup.py`, so tilt sits above the arm angle in all three. Blue is always the
machine and orange is always the simulation, here and in every other figure of this
experiment.

Two overlays are drawn when their files exist and skipped when they do not, so each
figure builds from its capture alone. The solid orange is the same policy's from-rest
episode in the simulation. The dashed darker orange, on the first figure only, is the
simulated plant driven by the bench's own arm motion (`simulation/replay_run0.csv`).
With the same input as the machine and a different plant, the replay separates the plant
from the policy. ADR-0006 came out of it.

    just figures 06
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

COUNTS_PER_REV = 2400
MICROSTEPS_PER_REV = 3200
SPAN_S = 3.0  # the window the board logs at the full control rate
# The hold numbers are taken from here to the end of the capture, the same window
# `plot_swingup.py` reports the simulated hold over. Reading them from the end of the
# dense window instead, which is where the log's sample rate changes, starts them 39 ms
# after the arrival and puts the settling transient in the statistics.
HOLD_FROM_S = 5.0

# The plot is pinned to these figure fractions and written without the tight crop, so
# the two bench figures share an axes width whatever their legends and labels measure.
# Cropped tight, the first figure's three-entry legend had widened its canvas to 1254 px
# against the second's 1198, and the write-up puts the two one after the other.
FIG_SIZE_IN = (8.2, 5.9)
MARGINS = dict(left=0.105, right=0.975, top=0.80, bottom=0.105, hspace=0.13)


def load_capture(path: Path, attempt: int) -> dict[str, list[float]]:
    """One attempt of a capture: time, tilt from vertical, arm angle."""
    attempts: list[list[tuple[int, int, int]]] = []
    last_us = None
    for line in path.read_text(errors="replace").splitlines():
        fields = line.rstrip("\r").split("\t")
        # Two layouts: the replay input, `seq us counts phi D`, and the raw mode r
        # capture, whose log rows are `<blank> us counts phi cmd R`.
        if not (
            len(fields) == 5
            and fields[4] == "D"
            or len(fields) == 6
            and fields[5] == "R"
        ):
            continue
        try:
            us, counts, phi = int(fields[1]), int(fields[2]), int(fields[3])
        except ValueError:
            continue
        if last_us is None or us < last_us:
            attempts.append([])
        last_us = us
        attempts[-1].append((us, counts, phi))
    rows = attempts[attempt]
    t0 = 0  # the board's attempt clock, which the logbook and write-up quote
    tilt = []
    for _, counts, _ in rows:
        hanging = counts * 2 * math.pi / COUNTS_PER_REV
        from_upright = math.atan2(
            math.sin(hanging - math.pi), math.cos(hanging - math.pi)
        )
        tilt.append(math.degrees(from_upright))
    return {
        "t_s": [(us - t0) / 1e6 for us, _, _ in rows],
        "tilt_deg": tilt,
        "arm_rad": [phi * 2 * math.pi / MICROSTEPS_PER_REV for _, _, phi in rows],
    }


def load_csv(path: Path) -> dict[str, list[float]]:
    """Read a csv into float columns, leaving out columns that are not numbers."""
    columns: dict[str, list[float]] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh):
            for key, value in row.items():
                try:
                    columns.setdefault(key, []).append(float(value))
                except ValueError:
                    columns.pop(key, None)
    return columns


def rms(values: list[float]) -> float:
    """Root mean square, for the tilt of a hold."""
    return math.sqrt(sum(v * v for v in values) / len(values))


FIGURES = (
    {
        "capture": "hardware/rl_swingup_20260910.tsv",
        "attempt": 0,
        "trace": "simulation/trace_r3_clock_seed1.csv",
        "replay": "simulation/replay_run0.csv",
        "output": "bench_first_run.png",
        "title": "The swing-up transferred; the catch did not",
        "subtitle": (
            "The clock-jittered policy on the bench, 2026-09-10, attempt 1 of three."
        ),
        "held": False,
    },
    {
        "capture": "hardware/rl_swingup_20260910_session2.tsv",
        "attempt": 1,
        "trace": "simulation/trace_r6_armspeed_seed1.csv",
        "replay": None,
        "output": "bench_second_run.png",
        "title": "A slower arm catches it",
        "subtitle": (
            "The slow-arm policy on the bench, Session 2,"
            " attempt 2 of the two captured."
        ),
        "held": True,
    },
)


def main() -> int:
    """Draw each figure in FIGURES beside this script."""
    _style.apply_style()
    for spec in FIGURES:
        draw(**spec)
    return 0


def draw(
    *,
    capture: str,
    attempt: int,
    trace: str,
    replay: str | None,
    output: str,
    title: str,
    subtitle: str,
    held: bool,
) -> None:
    """Draw the two panels for one bench attempt and write the figure."""
    bench = load_capture(EXPERIMENT / capture, attempt)
    t = bench["t_s"]
    tilt = [abs(v) for v in bench["tilt_deg"]]
    window = [i for i, v in enumerate(t) if v <= SPAN_S]
    tail = [i for i, v in enumerate(t) if v > SPAN_S]

    arrive = next(
        (t[i] for i in window if round(tilt[i], 6) < _style.CAPTURE_DEG), None
    )
    fall = None
    if arrive is not None:
        fall = next(
            (t[i] for i in window if t[i] > arrive and tilt[i] >= _style.FALL_DEG),
            None,
        )

    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=FIG_SIZE_IN, sharex=True, height_ratios=[1.3, 1]
    )

    top.plot(
        [t[i] for i in window],
        [tilt[i] for i in window],
        color=_style.BENCH,
        lw=2.1,
        zorder=6,
        label="on the bench",
    )
    # Only the tilt panel's legend is built, so the arm panel's series go unlabelled
    # and the arm's provenance is carried by its y-axis label instead.
    bottom.plot(
        [t[i] for i in window],
        [bench["arm_rad"][i] for i in window],
        color=_style.BENCH,
        lw=2.1,
        zorder=6,
    )

    sim_arrive = None
    sim_path = EXPERIMENT / trace
    if sim_path.exists():
        sim = load_csv(sim_path)
        sim_arrive = next(
            (
                sim["t_s"][i]
                for i, v in enumerate(sim["tilt_deg"])
                if abs(v) <= _style.CAPTURE_DEG
            ),
            None,
        )
        keep = [i for i, v in enumerate(sim["t_s"]) if v <= SPAN_S]
        top.plot(
            [sim["t_s"][i] for i in keep],
            [abs(sim["tilt_deg"][i]) for i in keep],
            color=_style.SIM,
            lw=1.7,
            zorder=5,
            label="the same policy in simulation",
        )
        bottom.plot(
            [sim["t_s"][i] for i in keep],
            [sim["rotor_rad"][i] for i in keep],
            color=_style.SIM,
            lw=1.7,
            zorder=5,
        )

    note = None
    replay_path = EXPERIMENT / replay if replay else None
    if replay_path is not None and replay_path.exists():
        replayed = load_csv(replay_path)
        replay_tilt = [abs(v) for v in replayed["sim_tilt_deg"]]
        top.plot(
            replayed["t_s"],
            replay_tilt,
            color=_style.SIM_REPLAY,
            lw=1.7,
            ls=(0, (6, 3)),
            zorder=4,
            label="the simulated plant, driven by the bench's own arm",
        )
        early = next(
            (
                replayed["t_s"][i]
                for i, v in enumerate(replay_tilt)
                if v <= _style.CAPTURE_DEG
            ),
            None,
        )
        if early is not None and arrive is not None:
            note = (
                f"given the bench's own arm motion, the simulated plant\n"
                f"reached 3 deg {arrive - early:.2f} s early and then went over the top"
            )

    _style.tilt_axis(top, fall=True)
    _style.arm_axis(bottom)
    # The board has no arm encoder: the blue arm trace is integrated from the microsteps
    # it commanded. The replay in the write-up rests on that dead reckoning being the
    # real motion, so the axis says where the number comes from.
    bottom.set_ylabel("arm angle (rad)\nbench dead-reckoned")

    if arrive is not None:
        for ax in (top, bottom):
            _style.event_rule(ax, arrive)
        _style.event_label(top, arrive, f"inside 3 deg at {arrive:.2f} s")
    if fall is not None:
        for ax in (top, bottom):
            _style.event_rule(ax, fall)
        _style.event_label(top, fall, f"past 30 deg at {fall:.2f} s", side="right")

    if held and tail:
        hold = [abs(bench["tilt_deg"][i]) for i in tail if t[i] >= HOLD_FROM_S]
        note = (
            f"from {HOLD_FROM_S:.0f} s to the end of the {t[-1]:.0f} s capture"
            f"\nthe tilt runs {rms(hold):.2f} deg rms and never passes"
            f" {max(hold):.2f} deg"
        )
        if sim_arrive is not None and sim_arrive > SPAN_S:
            note += (
                "\nin simulation the same policy arrives at"
                f" {sim_arrive:.2f} s, past this window"
            )

    # The note goes in the arm panel's empty lower band. Nothing the policy does takes
    # the arm below -1 rad after a stroke.
    if note:
        _style.readout(bottom, note, y=0.21)

    bottom.set_xlabel("time from the first policy step (s)")
    bottom.set_xlim(0, SPAN_S)
    bottom.set_xticks([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])

    _style.titled(top, title, subtitle, pad=72, subtitle_y=1.245)
    # Two columns. In one row these labels measure wider than the plot they sit over,
    # and on a fixed canvas the last of them runs off the page.
    top.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.004),
        ncol=2,
        frameon=False,
        fontsize=10,
        labelcolor=_style.MUTED,
        handlelength=2.1,
        columnspacing=1.8,
        borderpad=0.0,
    )
    fig.align_ylabels((top, bottom))
    fig.subplots_adjust(**MARGINS)
    # `bbox_inches=None` would fall back to the rcParam, which is the tight crop this
    # has to avoid. The figure's own bbox is the way to say "write the whole canvas".
    _style.save(fig, HERE / output, bbox_inches=fig.bbox_inches, pad_inches=0.0)
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())

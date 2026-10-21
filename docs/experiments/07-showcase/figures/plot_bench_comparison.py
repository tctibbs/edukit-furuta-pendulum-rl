# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Every carousel attempt on the bench, by how long the pendulum stayed up.

One row per entry, one dot per attempt, read from the `SHOWCASE` lines of every
capture under `hardware/` (the identification image's capture aside). An attempt
belongs to the entry named by the `SHOWCASE entry` line before it. A stock entry's time
is how long the kit's loop ran after its handover: the `RL STOP` line's milliseconds,
or the result line's `run` where the first image printed no `RL STOP`. A learned
entry's time is the result line's `hold`. Each row's label carries its swing-up time,
from the result lines' `up`. The LQR row fills in from the first capture that holds an
LQR attempt.

    just figures 07
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

ENTRY = re.compile(r"SHOWCASE entry \d+/\d+ (?P<title>[A-Z0-9 -]+?) attempt")
RESULT = re.compile(
    r"SHOWCASE result \d+ (?P<title>[A-Z0-9 -]+?): (?P<outcome>[A-Z ]+?)(?: [\d.]+s)?"
    r" up (?P<up>\d+) hold (?P<hold>\d+) run (?P<run>\d+)"
)
KIT_EXIT = re.compile(r"Error Exit (?:Encoder|Motor) Position Exceeded")
STOP_MS = re.compile(r"RL STOP after \d+ cycles \((?P<ms>\d+) ms\)")

STOCK = ("PID", "LQR")
ROWS = ("PID", "LQR", "BALANCE", "SWING-UP", "JETHRO")
KIT_SWING_UP = ("PID", "LQR", "BALANCE")
DESCRIPTIONS = {
    "PID": "the kit's swing-up{up}, then its PID",
    "LQR": "the kit's swing-up{up}, then its LQR",
    "BALANCE": "the kit's swing-up{up}, then a learned policy",
    "SWING-UP": "a learned swing-up, up in{up}",
    "JETHRO": "a learned swing-up with a gentler arm, up in{up}",
}
COLOURS = {
    "PID": _style.PID,
    "LQR": _style.LQR,
    "BALANCE": _style.CATCH_POLICY,
    "SWING-UP": _style.SWINGUP,
    "JETHRO": _style.JETHRO,
}
# How each result word the firmware prints ends an attempt (board/showcase.c).
STILL_UP = {"HELD", "STOPPED"}
ENDED = {"FELL", "CENTER ARM", "CHECK ARM", "FAULT", "LOOP LAG", "UNWIND ARM"}
NEVER_UP = {"NO CATCH"}
# Attempts singled out on the figure, by capture and entry.
NOTES = {("showcase_20260913_level_base.tsv", "PID"): "after leveling"}

TICKS = ((0.5, "0.5 s"), (1, "1 s"), (10, "10 s"), (60, "1 min"), (300, "5 min"))
LANES = (0.0, 0.2, -0.2, 0.4)
NOTE_LANE = -0.4  # a noted attempt sits on its own, its note beside it
GAP_DECADES = 0.065  # the closest two markers sit in one lane


@dataclass(frozen=True)
class Attempt:
    """One attempt: its entry, seconds up, whether it was still up, and where it was."""

    title: str
    seconds: float
    still_up: bool
    capture: str


def lines_of(path: Path) -> list[str]:
    """A capture's lines, without the carriage returns the serial link adds."""
    return [line.rstrip("\r") for line in path.read_text(errors="replace").splitlines()]


def captures() -> list[Path]:
    """The carousel captures, without the identification image's."""
    found = sorted((EXPERIMENT / "hardware").glob("showcase_*.tsv"))
    return [path for path in found if "sept4" not in path.name]


def outcome_of(word: str) -> bool | None:
    """True if the pendulum was still up when the attempt ended, None if never up."""
    if word in STILL_UP:
        return True
    if word in NEVER_UP:
        return None
    if word in ENDED:
        return False
    raise ValueError(f"no outcome mapping for result word {word!r}")


def read_capture(path: Path) -> tuple[list[Attempt], list[str], dict[str, list[float]]]:
    """A capture's attempts, the titles that never got up, and every swing-up time."""
    attempts: list[Attempt] = []
    never_up: list[str] = []
    ups: dict[str, list[float]] = {}
    title = stop_ms = None
    exited = counted = False
    for line in lines_of(path):
        entry = ENTRY.search(line)
        if entry:
            title, stop_ms, exited, counted = entry["title"], None, False, False
            continue
        if KIT_EXIT.search(line) and title in STOCK:
            exited = True
            continue
        stop = STOP_MS.search(line)
        if stop:
            stop_ms = int(stop["ms"])
            if exited:  # a kit limit ended it; its result line, if any, adds nothing
                attempts.append(Attempt(title, stop_ms / 1e3, False, path.name))
                exited, counted = False, True
            continue
        result = RESULT.search(line)
        if not result or result["title"] not in ROWS:
            continue
        name = result["title"]
        if int(result["up"]) > 0:
            ups.setdefault(name, []).append(int(result["up"]) / 1e3)
        if counted:
            pass
        elif exited:  # a kit limit with no RL STOP line: the first image
            attempts.append(Attempt(name, int(result["run"]) / 1e3, False, path.name))
        else:
            still_up = outcome_of(result["outcome"])
            if still_up is None:
                never_up.append(name)
            elif name in STOCK:
                ms = stop_ms if stop_ms is not None else int(result["run"])
                attempts.append(Attempt(name, ms / 1e3, still_up, path.name))
            else:
                hold_s = int(result["hold"]) / 1e3
                attempts.append(Attempt(name, hold_s, still_up, path.name))
        title, stop_ms, exited, counted = None, None, False, False
    return attempts, never_up, ups


def bench() -> tuple[list[Attempt], list[str], dict[str, list[float]]]:
    """Every capture's attempts, never-up titles, and swing-up times, together."""
    attempts: list[Attempt] = []
    never_up: list[str] = []
    ups: dict[str, list[float]] = {}
    for path in captures():
        found, missed, times = read_capture(path)
        attempts += found
        never_up += missed
        for name, values in times.items():
            ups.setdefault(name, []).extend(values)
    return attempts, never_up, ups


def span(values: list[float]) -> str:
    """A time or a range of times, to a tenth of a second."""
    low, high = f"{min(values):.1f}", f"{max(values):.1f}"
    return f" {low} s" if low == high else f" {low} to {high} s"


def label_of(name: str, ups: dict[str, list[float]]) -> str:
    """The row's description, with its swing-up time where the bench recorded one."""
    if name in KIT_SWING_UP:
        kit = [t for row in KIT_SWING_UP for t in ups.get(row, [])]
        up = f",{span(kit)}" if kit and name in ups else ""
    else:
        up = span(ups[name]) if name in ups else " (not recorded)"
    return DESCRIPTIONS[name].format(up=up)


def lanes(xs: list[float]) -> list[float]:
    """A vertical offset per marker, so markers closer than one width stack."""
    last: dict[float, float] = {}
    offsets = []
    for x in xs:
        here = math.log10(x)
        lane = next(
            (o for o in LANES if o not in last or here - last[o] > GAP_DECADES),
            LANES[-1],
        )
        last[lane] = here
        offsets.append(lane)
    return offsets


def main() -> None:
    """Draw one row per entry and one marker per attempt."""
    _style.apply_style()
    attempts, never_up, ups = bench()
    seconds = [a.seconds for a in attempts]
    low = min(0.3, 0.7 * min(seconds))
    high = max(600.0, 1.5 * max(seconds))

    fig, ax = plt.subplots(figsize=(8.8, 4.7))
    fig.subplots_adjust(left=0.36, right=0.98, top=0.97, bottom=0.2)
    for row, name in enumerate(ROWS):
        y = len(ROWS) - 1 - row
        mine = sorted((a for a in attempts if a.title == name), key=lambda a: a.seconds)
        noted = [a for a in mine if (a.capture, name) in NOTES]
        plain = [a for a in mine if (a.capture, name) not in NOTES]
        placed = list(zip(plain, lanes([a.seconds for a in plain]), strict=True))
        placed += [(a, NOTE_LANE) for a in noted]
        colour = COLOURS[name]
        for attempt, offset in placed:
            ax.plot(
                attempt.seconds,
                y + offset,
                ">" if attempt.still_up else "o",
                ms=8 if attempt.still_up else 7,
                mfc=colour if attempt.still_up else _style.SURFACE,
                mec=colour,
                mew=1.6,
                zorder=3,
            )
            note = NOTES.get((attempt.capture, name))
            if note:
                ax.annotate(
                    note,
                    (attempt.seconds, y + offset),
                    xytext=(9, 0),
                    textcoords="offset points",
                    ha="left",
                    va="center",
                    fontsize=8.5,
                    color=_style.MUTED,
                )
        missed = never_up.count(name)
        count = f"{len(mine)} attempt{'s' * (len(mine) != 1)}"
        if missed:
            count += f", {missed} never up"
        ax.text(
            -0.02,
            y + 0.12,
            name,
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="bottom",
            fontsize=10.5,
            weight="bold",
            color=_style.INK,
        )
        ax.text(
            -0.02,
            y + 0.08,
            label_of(name, ups) + (f"\n{count}" if mine or missed else ""),
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="top",
            fontsize=8.8,
            color=_style.MUTED,
            linespacing=1.25,
        )
        if not mine and not missed:
            ax.text(
                math.sqrt(low * high),
                y,
                "not run on the bench yet",
                ha="center",
                va="center",
                fontsize=9,
                style="italic",
                color=_style.MUTED,
            )

    ax.set_xscale("log")
    ax.set_xlim(low, high)
    ax.set_xticks([t for t, _ in TICKS])
    ax.set_xticklabels([label for _, label in TICKS])
    ax.minorticks_off()
    ax.set_ylim(-0.6, len(ROWS) - 0.4)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("how long the pendulum stayed up after reaching upright (log scale)")
    key = [
        Line2D([], [], ls="", marker=">", ms=8, mfc=_style.MUTED, mec=_style.MUTED),
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            ms=7,
            mfc=_style.SURFACE,
            mec=_style.MUTED,
            mew=1.6,
        ),
    ]
    fig.legend(
        key,
        [
            "still up when stopped, so up at least this long",
            "fell, or a limit stopped it",
        ],
        loc="lower center",
        bbox_to_anchor=(0.66, 0.0),
        ncol=2,
        fontsize=9,
        handletextpad=0.3,
        columnspacing=1.6,
        labelcolor=_style.MUTED,
    )
    _style.save(fig, HERE / "bench_comparison.png")


if __name__ == "__main__":
    main()

"""Tests for the showcase's board code.

The display, the button, the buzzer, one attempt's statistics, the carousel, the
screens, and the generator that writes the carousel's table.

The code is pure C with no I/O, so these compile it into a host harness
(`board/test_showcase.c`) and script it. The expected timings are worked out from the
constants in `board/showcase.h` rather than read back from a run, so a change to the
debounce or a tune shows up here as a failure to explain, not a number to copy.

The compiler is the host's (tests/conftest.py). Nothing here touches the firmware
toolchain.
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "board"
SOURCES = [
    BOARD / name
    for name in (
        "display.c",
        "font5x7.c",
        "showcase.c",
        "showcase_screens.c",
        "showcase_table.c",
        "policy.c",
        "test_showcase.c",
    )
]


@pytest.fixture(scope="module")
def harness(build_harness: Callable[..., Path]) -> Path:
    """The host harness, built with the board code's warning flags."""
    return build_harness("test_showcase", SOURCES, [f"-I{BOARD}"])


def run(harness: Path, *args: str, stdin: str = "") -> list[str]:
    """One harness mode's output lines."""
    result = subprocess.run(
        [str(harness), *args], input=stdin, capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


# Display.


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [(0, 0, ["0 0"]), (5, 10, ["133 2"]), (127, 63, ["1023 7"]), (128, 0, [])],
)
def test_pixel_lands_in_the_panels_page_and_column(
    harness: Path, x: int, y: int, expected: list[str]
) -> None:
    """A pixel is bit `y % 8` of byte `(y // 8) * 128 + x`; off the panel it is dropped.

    That is the SSD1306's horizontal addressing order, page by page, bit 0 the page's
    top row, so a frame sent in buffer order lands where it was drawn.
    """
    assert run(harness, "pixel", str(x), str(y)) == expected


def test_init_packet_configures_a_128_by_64_charge_pump_panel(harness: Path) -> None:
    """Command prefix, display off first and on last, 64 rows, the charge pump on."""
    packet = run(harness, "init")[0]
    assert packet.startswith("00 AE ")
    assert packet.endswith(" AF")
    assert " A8 3F " in packet
    assert " 8D 14 " in packet


def test_flush_sends_the_window_then_the_whole_frame(harness: Path) -> None:
    """Two transmissions: the full column and page window, then 1024 bytes of data."""
    assert run(harness, "flush") == [
        "7 00 21 00 7F 22 00 07",
        "1025 40 01 00 00 00 00 00 00",
    ]


@pytest.mark.parametrize(
    ("scale", "length", "clipped"),
    [(1, 21, 0), (1, 22, 1), (2, 10, 0), (2, 11, 1)],
)
def test_text_reports_the_characters_that_do_not_fit(
    harness: Path, scale: int, length: int, clipped: int
) -> None:
    """21 characters fit a line at scale 1 and 10 at scale 2.

    The next one is counted.
    """
    count, lit = (
        int(v) for v in run(harness, "text", str(scale), "W" * length)[0].split()
    )
    assert count == clipped
    assert lit > 0


# Button.


def samples(*runs: tuple[int, int]) -> str:
    """Millisecond samples from `(level, duration)` runs."""
    return "".join(f"{level}\n" * duration for level, duration in runs)


def test_bounce_shorter_than_the_debounce_is_no_press(harness: Path) -> None:
    """Contact bounce, level changes a millisecond apart, never reaches 20 ms stable."""
    bounce = tuple((k % 2, 1) for k in range(40))
    assert run(harness, "button", stdin=samples((0, 100), *bounce, (0, 100))) == []


def test_a_tap_is_one_short_press_on_release(harness: Path) -> None:
    """Pressed at 100 ms and accepted 20 ms later.

    Released at 160 and accepted at 180.
    """
    assert run(harness, "button", stdin=samples((0, 100), (1, 60), (0, 100))) == [
        "180 SHORT"
    ]


def test_a_hold_is_one_long_press_and_no_short(harness: Path) -> None:
    """Accepted at 120 ms, LONG once it has been held 1000 ms, nothing on release."""
    assert run(harness, "button", stdin=samples((0, 100), (1, 1500), (0, 100))) == [
        "1119 LONG"
    ]


def test_two_taps_are_two_presses(harness: Path) -> None:
    """Two 60 ms taps 100 ms apart."""
    stdin = samples((0, 50), (1, 60), (0, 100), (1, 60), (0, 100))
    assert run(harness, "button", stdin=stdin) == ["130 SHORT", "290 SHORT"]


def test_a_button_held_from_boot_does_nothing_until_released(harness: Path) -> None:
    """Held for 3 s from the first sample: no LONG at 1 s and no SHORT on release.

    That is a stuck pin, or a finger on the button through a reset. Once it has read
    released for the debounce time it works, and a tap after that is an ordinary press.
    """
    stdin = samples((1, 3000), (0, 100), (1, 60), (0, 100))
    assert run(harness, "button", stdin=stdin) == ["3180 SHORT"]


# Buzzer.


@pytest.mark.parametrize(
    ("sound", "changes"),
    [
        ("MODE", ["0 1319", "25 1760", "70 0"]),
        ("NEWER", ["0 1760", "25 1319", "70 0"]),
        ("DIVE", ["0 1568", "35 1319", "70 1047", "140 0"]),
        ("CLIMB", ["0 1047", "35 1319", "70 1568", "140 0"]),
        ("SWAP", ["0 1568", "25 2093", "50 1568", "90 0"]),
        ("SWAP_BACK", ["0 2093", "25 1568", "50 2093", "90 0"]),
        ("TICK", ["0 2093", "6 0"]),
        ("READY", ["0 1319", "40 0"]),
        ("ALARM", ["0 880", "90 0", "160 880", "250 0", "320 880", "410 0"]),
    ],
)
def test_held_note_tunes_change_on_the_millisecond_and_end_silent(
    harness: Path, sound: str, changes: list[str]
) -> None:
    """Each note holds for exactly its duration.

    Every tune ends with the output off.
    """
    assert run(harness, "buzzer", sound) == changes


def test_catch_is_two_rising_glides(harness: Path) -> None:
    """The double chirp.

    1600 to 2400 Hz over 50 ms, 40 ms of rest, 1800 to 3000 Hz over 70 ms, then 50 ms
    held at 3000 more quietly, a loudness change with the same pitch.
    """
    changes = run(harness, "buzzer", "CATCH")
    assert changes[0] == "0 1600"
    for expected in ("49 2400", "50 0", "90 1800", "159 3000", "160 3000"):
        assert expected in changes
    assert changes[-1] == "210 0"
    first_glide = [
        int(line.split()[1]) for line in changes if int(line.split()[0]) < 50
    ]
    assert first_glide == sorted(first_glide) and len(first_glide) == 50


def test_fall_is_one_falling_glide(harness: Path) -> None:
    """The sigh: 1100 down to 500 Hz over 300 ms, then a quieter 60 ms at 500."""
    changes = run(harness, "buzzer", "FALL")
    assert changes[0] == "0 1100"
    assert "299 500" in changes and "300 500" in changes
    assert changes[-1] == "360 0"


@pytest.mark.parametrize(
    ("count", "history", "changes"),
    [
        (3, 0, ["0 1760", "60 0", "180 1760", "240 0", "360 1760", "420 0"]),
        (2, 1, ["0 1760", "60 0", "180 1760", "240 0", "360 880", "560 0"]),
        (0, 0, ["0 1760", "60 0"]),
        (
            40,
            0,
            [
                f"{180 * k} 1760" if i == 0 else f"{180 * k + 60} 0"
                for k in range(9)
                for i in range(2)
            ],
        ),
    ],
)
def test_mode_number_beeps(
    harness: Path, count: int, history: int, changes: list[str]
) -> None:
    """With no display, the mode is beeped.

    A 60 ms beep every 180 ms, once per step of the number, clamped to 1 to 9, then a
    200 ms low tone for a history entry.
    """
    assert run(harness, "beeps", str(count), str(history)) == changes


# One attempt.


def attempt(harness: Path, outcome: str, cycles: list[tuple[int, int, float]]) -> dict:
    """Run the attempt statistics over `(counts, steps, cmd)` cycles."""
    lines = run(
        harness,
        "attempt",
        outcome,
        stdin="".join(f"{c} {s} {m}\n" for c, s, m in cycles),
    )
    fields = dict(line.split(" ", 1) for line in lines)
    return {k: (v if k == "text" else int(v)) for k, v in fields.items()}


def test_a_swing_up_and_hold_reads_its_arrival_and_hold(harness: Path) -> None:
    """Hanging for 1 s, then upright for 6 s.

    Up at 1.0 s, held 6.0 s, no pass over the top.
    """
    cycles = [(0, 0, 0.0)] * 500 + [(1200, 0, 0.0)] * 3000
    r = attempt(harness, "HELD", cycles)
    assert (r["arrived"], r["up_ms"], r["hold_ms"], r["run_ms"], r["tops"]) == (
        1,
        1000,
        5998,
        7000,
        0,
    )
    assert r["text"] == "HELD 6.0s|up 1.0s   held 0/1"


@pytest.mark.parametrize("direction", [1, -1])
def test_going_over_the_top_counts_one_pass(harness: Path, direction: int) -> None:
    """A sweep from one hanging position to the next, either way round, is one top.

    It arrives within 3 degrees at count 1181 and leaves 30 degrees at count 1400, so it
    held for 219 cycles; a spin outranks the arrival time in the small line.
    """
    cycles = [(direction * c, 0, 0.0) for c in range(0, 2401)]
    r = attempt(harness, "FELL", cycles)
    assert (r["arrived"], r["tops"], r["hold_ms"]) == (1, 1, 438)
    assert r["text"] == "FELL 0.4s|spun 1x   held 0/1"


def test_a_wobble_about_upright_is_not_a_pass_over_the_top(harness: Path) -> None:
    """Swinging 22 degrees either side of upright never gets near a hanging position."""
    cycles = [(0, 0, 0.0)] * 10 + [
        (1200 + (150 if k % 2 else -150), 0, 0.0) for k in range(1000)
    ]
    assert attempt(harness, "HELD", cycles)["tops"] == 0


def test_hold_is_the_longest_unbroken_stretch_upright(harness: Path) -> None:
    """Up for 2 s, fallen past 30 degrees for 1 s, back up for 4 s.

    The hold is the 4 s stretch, not arrival to the last cycle upright, which would read
    7 s.
    """
    cycles = (
        [(0, 0, 0.0)] * 10
        + [(1200, 0, 0.0)] * 1000
        + [(1200 + 400, 0, 0.0)] * 500
        + [(1200, 0, 0.0)] * 2000
    )
    r = attempt(harness, "FELL", cycles)
    assert (r["arrived"], r["hold_ms"]) == (1, 3998)


def test_a_press_does_not_hide_a_stop_the_operator_must_act_on(harness: Path) -> None:
    """A travel stop, a stall or a fault pauses for its own reason.

    It does so even when a press ended the attempt, so the screen still says to unwind
    or check the arm.
    """
    commands = [
        "at 4000",
        "end TRAVEL 0 tap",
        "tap",
        "at 8000",
        "end STALL 0 hold",
        "tap",
        "at 12000",
        "end FAULT 0 tap",
    ]
    lines = run(harness, "carousel", stdin="\n".join(commands) + "\n")
    assert [line.split()[2] for line in lines if line.startswith("PAUSED")] == [
        "pause=TRAVEL",
        "pause=STALL",
        "pause=FAULT",
    ]


def test_command_reversals_count_only_above_the_threshold(harness: Path) -> None:
    """A 10 rad/s^2 command flipping every cycle reverses 99 times in 100.

    A 2 rad/s^2 one is under the 5 rad/s^2 floor and reverses none.
    """
    strong = [(0, 0, 10.0 if k % 2 else -10.0) for k in range(100)]
    weak = [(0, 0, 2.0 if k % 2 else -2.0) for k in range(100)]
    assert attempt(harness, "NO_CATCH", strong)["flips"] == 99
    assert attempt(harness, "NO_CATCH", weak)["flips"] == 0


def test_a_run_that_never_arrives_says_only_the_tally(harness: Path) -> None:
    """No arrival: zero up and hold times, and the small line is the tally alone."""
    cycles = [(0, k, 0.0) for k in range(-4000, 0, 4)]
    r = attempt(harness, "NO_CATCH", cycles)
    assert (r["arrived"], r["up_ms"], r["hold_ms"], r["peak_steps"]) == (0, 0, 0, 4000)
    assert r["text"] == "NO CATCH|held 0/1"


# The carousel.


def state(phase: str, entry: str, **fields: object) -> str:
    """One harness state line, with the defaults most lines share."""
    values = {
        "pause": "NONE",
        "in_row": 0,
        "attempts": 0,
        "held": 0,
        "event": "NONE",
    }
    values.update(fields)
    return (
        f"{phase} entry={entry} pause={values['pause']} in_row={values['in_row']} "
        f"attempts={values['attempts']} held={values['held']} event={values['event']}"
    )


CAROUSEL_SCRIPT = [
    ("none", state("ARMING", "JETHRO")),
    ("tap", state("ARMING", "PID", event="MODE")),
    ("hold", state("ARMING", "LQR", event="SWAP")),
    ("hold", state("ARMING", "PID", event="SWAP")),
    ("hold", state("ARMING", "LQR", event="SWAP")),
    ("tap", state("ARMING", "RING-DOWN", event="MODE")),
    ("hold", state("ARMING", "FREE SWING", event="DIVE")),
    ("tap", state("ARMING", "TILT SWEEP", event="NEWER")),
    ("tap", state("ARMING", "RING-DOWN", event="CLIMB")),
    ("hold", state("ARMING", "FREE SWING", event="DIVE")),
    ("hold", state("ARMING", "RING-DOWN", event="CLIMB")),
    ("tap", state("ARMING", "BALANCE", event="MODE")),
    ("tap", state("ARMING", "SWING-UP", event="MODE")),
    ("tap", state("ARMING", "JETHRO", event="MODE")),
    ("hold", state("ARMING", "JETHRO", event="NO_HISTORY")),
    ("at 3999", state("ARMING", "JETHRO")),
    ("at 4000", state("RUNNING", "JETHRO", event="START")),
    ("end HELD 30000", state("ARMING", "JETHRO", in_row=1, attempts=1, held=1)),
    (
        "at 10000",
        state("RUNNING", "JETHRO", in_row=1, attempts=1, held=1, event="START"),
    ),
    (
        "end FELL 600 tap",
        state("PAUSED", "JETHRO", pause="BUTTON", in_row=2, attempts=2, held=1),
    ),
    (
        "hold",
        state(
            "ARMING",
            "JETHRO",
            in_row=2,
            attempts=2,
            held=1,
            event="NO_HISTORY",
        ),
    ),
    ("tap", state("ARMING", "PID", event="MODE")),
    ("at 14000", state("RUNNING", "PID", event="START")),
    ("end TRAVEL 0", state("PAUSED", "PID", pause="TRAVEL", in_row=1, attempts=1)),
    ("tap", state("ARMING", "PID", in_row=1, attempts=1, event="RESUME")),
    ("auto 2", state("ARMING", "PID", in_row=1, attempts=1)),
    ("at 18000", state("RUNNING", "PID", in_row=1, attempts=1, event="START")),
    ("end HELD 6000", state("ARMING", "LQR")),
]


def walk(harness: Path, script: list[tuple[str, str]]) -> None:
    """Run a carousel script and compare every state line with the expected one."""
    commands = [command for command, _ in script]
    expected = [line for _, line in script]
    assert run(harness, "carousel", stdin="\n".join(commands) + "\n") == expected


def test_carousel_session(harness: Path) -> None:
    """One scripted session over the planned table.

    It boots armed on Jethro, the last main mode, and a tap wraps to the first. A hold
    on PID swaps it with its variant, LQR, and back, in place; a tap from either moves
    to the next main mode. A hold on a mode with history dives to its oldest version;
    taps move to newer versions and past the newest back to the main mode; a hold climbs
    straight out. A hold on a mode with neither restarts the countdown. The countdown
    starts an attempt at 4 s; a result holds the screen 6 s before the next; a press
    that ends an attempt pauses on it, and a tap resumes the same mode; a travel stop
    pauses; and with auto-advance at two the carousel moves to the next entry in table
    order, the variant included, after the second attempt.
    """
    walk(harness, CAROUSEL_SCRIPT)


def test_a_hold_swaps_pid_and_lqr_in_place(harness: Path) -> None:
    """HOLD on PID selects LQR, and HOLD on LQR selects PID, each a SWAP.

    A swap is neither a dive nor a climb, so it plays its own sound and the screen
    never calls LQR part of PID's history.
    """
    walk(
        harness,
        [
            ("tap", state("ARMING", "PID", event="MODE")),
            ("hold", state("ARMING", "LQR", event="SWAP")),
            ("hold", state("ARMING", "PID", event="SWAP")),
        ],
    )


def test_a_hold_while_paused_swaps_too(harness: Path) -> None:
    """A hold on a paused PID swaps to LQR, as it does from the countdown."""
    walk(
        harness,
        [
            ("tap", state("ARMING", "PID", event="MODE")),
            ("at 4000", state("RUNNING", "PID", event="START")),
            (
                "end FELL 600 tap",
                state("PAUSED", "PID", pause="BUTTON", in_row=1, attempts=1),
            ),
            ("hold", state("ARMING", "LQR", event="SWAP")),
        ],
    )


def test_a_tap_from_lqr_moves_to_the_next_main_mode(harness: Path) -> None:
    """A variant sits on the main modes' level: a tap goes to RING-DOWN, not to PID."""
    walk(
        harness,
        [
            ("tap", state("ARMING", "PID", event="MODE")),
            ("hold", state("ARMING", "LQR", event="SWAP")),
            ("tap", state("ARMING", "RING-DOWN", event="MODE")),
        ],
    )


def test_a_hold_on_the_ring_down_dives_to_the_free_swing(harness: Path) -> None:
    """The ring-down leads the hardware tests, and the free swing comes next."""
    walk(
        harness,
        [
            ("tap", state("ARMING", "PID", event="MODE")),
            ("tap", state("ARMING", "RING-DOWN", event="MODE")),
            ("hold", state("ARMING", "FREE SWING", event="DIVE")),
        ],
    )


def test_every_entry_knows_where_it_sits(harness: Path) -> None:
    """Each entry's main mode, its group's history size, its position, its partner."""
    assert run(harness, "nav") == [
        "PID|PID|0|0|LQR",
        "LQR|PID|0|0|PID",
        "RING-DOWN|RING-DOWN|2|0|",
        "FREE SWING|RING-DOWN|2|1|",
        "TILT SWEEP|RING-DOWN|2|2|",
        "BALANCE|BALANCE|3|0|",
        "1ST CATCH|BALANCE|3|1|",
        "WANDERING|BALANCE|3|2|",
        "SHAKY HOLD|BALANCE|3|3|",
        "SWING-UP|SWING-UP|2|0|",
        "NEAR MISS|SWING-UP|2|1|",
        "FIRST HOLD|SWING-UP|2|2|",
        "JETHRO|JETHRO|0|0|",
    ]


def test_a_variant_is_not_history(harness: Path) -> None:
    """PID's group counts no history, and LQR has no history position.

    The screen and the sound tests below check what follows from it.
    """
    nav = {line.split("|")[0]: line.split("|")[1:] for line in run(harness, "nav")}
    assert nav["PID"][1:3] == ["0", "0"]
    assert nav["LQR"][1:3] == ["0", "0"]


SOUND_SCRIPT = [
    ("tap", "MODE MODE"),
    ("hold", "SWAP SWAP"),
    ("hold", "SWAP SWAP_BACK"),
    ("hold", "SWAP SWAP"),
    ("tap", "MODE MODE"),
    ("hold", "DIVE DIVE"),
    ("tap", "NEWER NEWER"),
    ("tap", "CLIMB CLIMB"),
    ("hold", "DIVE DIVE"),
    ("hold", "CLIMB CLIMB"),
    ("tap", "MODE MODE"),
    ("tap", "MODE MODE"),
    ("tap", "MODE MODE"),
    ("hold", "NO_HISTORY TICK"),
    ("at 4000", "START READY"),
    ("end FELL 600 tap", "NONE NONE"),
    ("tap", "RESUME READY"),
]


def test_each_selector_event_plays_its_own_sound(harness: Path) -> None:
    """A swap sounds neither like a dive nor like a climb, and says which way it went.

    Into LQR it plays SWAP and back to PID SWAP_BACK, two tunes that go there and back
    between two pitches in opposite directions, so the armed entry can be told by ear
    with no display. Every other event keeps its own sound.
    """
    commands = [command for command, _ in SOUND_SCRIPT]
    got = run(harness, "sounds", stdin="\n".join(commands) + "\n")
    assert got == [expected for _, expected in SOUND_SCRIPT]
    swaps = [line.split()[1] for line in got if line.startswith("SWAP")]
    assert swaps == ["SWAP", "SWAP_BACK", "SWAP"]
    assert not {"DIVE", "CLIMB"} & set(swaps)


def screen(
    layout: str,
    top_left: str,
    big: str,
    *,
    top_right: str = "",
    title: str = "",
    detail: str = "",
    hints: tuple[str, str] = ("", ""),
    pips: str = "",
) -> str:
    """One harness screen line. `pips` is `filled/count`, empty for a mode of one."""
    fields = [layout, top_left, top_right, title, big, detail, *hints, pips]
    return "|".join(fields)


SCREEN_SCRIPT = [
    ("none", screen("ARMED", "5/5", "JETHRO", hints=("tap next", ""))),
    ("tap", screen("ARMED", "1/5", "PID", hints=("tap next", "hold LQR"), pips="1/2")),
    ("hold", screen("ARMED", "1/5", "LQR", hints=("tap next", "hold PID"), pips="2/2")),
    ("hold", screen("ARMED", "1/5", "PID", hints=("tap next", "hold LQR"), pips="1/2")),
    (
        "tap",
        screen(
            "ARMED", "2/5", "RING-DOWN", hints=("tap next", "hold tests"), pips="1/3"
        ),
    ),
    (
        "hold",
        screen(
            "ARMED", "2/5", "FREE SWING", hints=("tap next", "hold exit"), pips="2/3"
        ),
    ),
    ("at 4000", None),
    (
        "running",
        screen("RUNNING", "2/5", "FREE SWING", detail="running", pips="2/3"),
    ),
    (
        "running lift",
        screen("RUNNING", "2/5", "FREE SWING", detail="lift, then let go", pips="2/3"),
    ),
    (
        "measured 1168 -",
        screen(
            "RESULT_PAUSED",
            "2/5",
            "1.168 Hz",
            title="FREE SWING",
            detail="run 1",
            hints=("tap to run again", ""),
            pips="2/3",
        ),
    ),
    (
        "hold",
        screen(
            "ARMED", "2/5", "RING-DOWN", hints=("tap next", "hold tests"), pips="1/3"
        ),
    ),
    (
        "tap",
        screen(
            "ARMED", "3/5", "BALANCE", hints=("tap next", "hold history"), pips="1/4"
        ),
    ),
    (
        "hold",
        screen(
            "ARMED", "3/5", "1ST CATCH", hints=("tap newer", "hold exit"), pips="2/4"
        ),
    ),
    (
        "hold",
        screen(
            "ARMED", "3/5", "BALANCE", hints=("tap next", "hold history"), pips="1/4"
        ),
    ),
    (
        "tap",
        screen(
            "ARMED", "4/5", "SWING-UP", hints=("tap next", "hold history"), pips="1/3"
        ),
    ),
    ("tap", screen("ARMED", "5/5", "JETHRO", hints=("tap next", ""))),
    ("hold", screen("ARMED", "5/5", "JETHRO", hints=("tap next", ""))),
    # 2 s into the countdown the hints are gone.
    ("at 6000", screen("ARMED", "5/5", "JETHRO")),
]


def test_screens_say_where_you_are_and_what_to_press(harness: Path) -> None:
    """Every armed screen's header, title and hints, word for word, and a test's cue.

    The header is the mode, "1/5", and one pip per member of the mode, the shown one
    filled: PID and LQR are the two pips of mode 1, and a history entry is a later pip
    of its main mode's. The hints stay up for the first moment of a countdown and then
    clear; PID and LQR name each other on the hold hint, a history entry reads tap newer
    and hold exit, the first hardware test reads hold tests and the others tap next, and
    a hold on a main mode with neither changes nothing on the screen. The running
    screen keeps the entry's title, the free swing's asks for the lift only when the cue
    is given, and a test's result names its entry above the number and stays up with
    the hint to run it again.
    """
    commands = [command for command, _ in SCREEN_SCRIPT]
    got = run(harness, "screen", stdin="\n".join(commands) + "\n")
    for (command, expected), line in zip(SCREEN_SCRIPT, got, strict=True):
        if expected is not None:
            assert line == expected, command


def test_lqr_is_never_called_history(harness: Path) -> None:
    """No screen of PID's group says HISTORY, and each says which of the two it is.

    Armed, running, after a result or paused, the header is mode 1 with PID the first
    pip and LQR the second, and a running screen or a result names its controller, so
    an LQR run never reads as a PID one.
    """
    commands = [
        "tap",
        "at 4000",
        "running",
        "end FELL 600",
        "hold",
        "at 20000",
        "running",
        "end HELD 6000 tap",
        "tap",
    ]
    lines = run(harness, "screen", stdin="\n".join(commands) + "\n")
    assert len(lines) == len(commands)
    fields = [line.split("|") for line in lines]
    assert all(f[1] == "1/5" for f in fields)
    assert not any("HISTORY" in line or "history" in line for line in lines)
    controller = {"1/2": "PID", "2/2": "LQR"}
    for command, f in zip(commands, fields, strict=True):
        layout, title, big, pips = f[0], f[3], f[4], f[8]
        assert pips in controller, command
        if layout == "RUNNING":
            assert big == controller[pips], command
        if layout.startswith("RESULT"):
            assert title == controller[pips], command
    assert [f[4] for f in fields if f[0] == "RUNNING"] == ["PID", "LQR"]


AUTO_SCRIPT = [
    ("tap", state("ARMING", "PID", event="MODE")),
    ("auto 1", state("ARMING", "PID")),
    ("at 4000", state("RUNNING", "PID", event="START")),
    ("end HELD 0", state("ARMING", "LQR")),
    ("at 10000", state("RUNNING", "LQR", event="START")),
    ("end NO_CATCH 0", state("ARMING", "RING-DOWN")),
    ("at 16000", state("RUNNING", "RING-DOWN", event="START")),
    ("end MEASURED 0", state("ARMING", "FREE SWING")),
    ("at 22000", state("RUNNING", "FREE SWING", event="START")),
    ("end NO_RELEASE 0", state("ARMING", "TILT SWEEP")),
    ("at 28000", state("RUNNING", "TILT SWEEP", event="START")),
    ("end MEASURED 0", state("ARMING", "BALANCE")),
]


def test_auto_advance_walks_every_entry_in_table_order(harness: Path) -> None:
    """Unattended, the carousel runs every row in turn, the variant and the tests too.

    Every entry starts when its countdown runs out; none is shown without running.
    """
    walk(harness, AUTO_SCRIPT)


def test_a_hardware_test_never_counts_as_held(harness: Path) -> None:
    """A test's tally is its runs alone, even with a hold time in its result."""
    walk(
        harness,
        [
            ("tap", state("ARMING", "PID", event="MODE")),
            ("tap", state("ARMING", "RING-DOWN", event="MODE")),
            ("at 4000", state("RUNNING", "RING-DOWN", event="START")),
            (
                "end MEASURED 6000",
                state("PAUSED", "RING-DOWN", pause="RESULT", in_row=1, attempts=1),
            ),
        ],
    )


@pytest.mark.parametrize("outcome", ["MEASURED", "NO_RELEASE", "NO_RESULT"])
def test_a_hardware_test_result_stays_up_until_a_press(
    harness: Path, outcome: str
) -> None:
    """A test runs once: its result stays up, and a tap runs it again.

    Left alone, a free swing would otherwise hold the rotor waiting 30 s for a hand
    every 40 s, and a tilt sweep would sweep a turn of travel every 70 s.
    """
    walk(
        harness,
        [
            ("tap", state("ARMING", "PID", event="MODE")),
            ("tap", state("ARMING", "RING-DOWN", event="MODE")),
            ("hold", state("ARMING", "FREE SWING", event="DIVE")),
            ("at 4000", state("RUNNING", "FREE SWING", event="START")),
            (
                f"end {outcome} 0",
                state("PAUSED", "FREE SWING", pause="RESULT", in_row=1, attempts=1),
            ),
            (
                "at 60000",
                state("PAUSED", "FREE SWING", pause="RESULT", in_row=1, attempts=1),
            ),
            (
                "tap",
                state("ARMING", "FREE SWING", in_row=1, attempts=1, event="RESUME"),
            ),
        ],
    )


# Hardware test results.


@pytest.mark.parametrize(
    ("probe", "outcome", "value", "detail", "attempts", "text"),
    [
        ("RINGDOWN", "MEASURED", 16234, "1170", 3, "Q 16.2|1.170 Hz   run 3"),
        ("RINGDOWN", "MEASURED", 28750, "1168", 1, "Q 28.8|1.168 Hz   run 1"),
        ("RINGDOWN", "MEASURED", 28750, "-", 1, "Q 28.8|run 1"),
        ("FREESWING", "MEASURED", 1168, "-", 1, "1.168 Hz|run 1"),
        ("TILT", "MEASURED", 510, "212000", 2, "TILT 0.51\x7f|bearing 212\x7f   run 2"),
        ("TILT", "MEASURED", 9994, "-500", 4, "TILT 9.99\x7f|bearing 359\x7f   run 4"),
        ("TILT", "MEASURED", 12340, "359600", 1, "TILT 12.3\x7f|bearing 0\x7f   run 1"),
        ("FREESWING", "NO_RELEASE", 0, "-", 2, "NO RELEASE|run 2"),
        ("RINGDOWN", "NO_RESULT", 0, "-", 1, "NO RESULT|run 1"),
        ("TILT", "NO_RESULT", 0, "-", 3, "NO RESULT|run 3"),
        ("RINGDOWN", "STALL", 0, "-", 1, "CHECK ARM|run 1"),
        ("TILT", "STOPPED", 510, "212000", 1, "STOPPED|run 1"),
        (
            "RINGDOWN",
            "MEASURED",
            2**31 - 1,
            str(-(2**31)),
            999,
            "Q 9999.9|-99.999 Hz   run 99",
        ),
    ],
)
def test_a_hardware_test_shows_its_number(
    harness: Path,
    probe: str,
    outcome: str,
    value: int,
    detail: str,
    attempts: int,
    text: str,
) -> None:
    """A test's result is its measured number, never a hold time or 'held n/m'.

    The ring-down shows Q_eff to a tenth with its frequency below, when the decay gave
    one; the free swing its frequency in Hz; the tilt its amplitude in hundredths of a
    degree under 10 and tenths above, with its bearing in whole degrees from 0 to 359.
    0x7F is the font's degree sign. A detail of `-` is a result without a second number,
    whose line then carries the run count alone, never a placeholder. A test that
    stopped short or could not measure shows why, and the run count alone. A wild
    number is held to what fits the line.
    """
    args = (probe, outcome, str(value), detail, str(attempts))
    assert run(harness, "format", *args) == [text]


# Screens.


OUTCOMES = 11  # SHOWCASE_OUTCOMES
PAUSES = 5  # BUTTON to NO_MOTOR; the RESULT pause is drawn once per outcome


def test_every_screen_fits_the_panel(harness: Path) -> None:
    """No text is clipped on any screen, and no two hints run into each other.

    Every entry armed, running with and without a cue, every outcome as a result and as
    a result kept up by a pause, and every other pause, over the planned table, the
    firmware's generated table, and a table with every title at its limit and
    worst-case numbers; and the boot screen. A main entry and variant one
    character over the title limit shows the overlap check counting: their hints need
    22 columns, and each armed screen reports one character over.
    """
    lines = run(harness, "screens")
    per_entry = 1 + 2 + 2 * OUTCOMES + PAUSES
    assert len(lines) == 3 * 13 * per_entry + 2 + 1
    clipped = {name: int(count) for name, count in (line.split() for line in lines)}
    over = {name: clipped.pop(name) for name in ("over-0-armed", "over-1-armed")}
    assert over == {"over-0-armed": 1, "over-1-armed": 1}
    assert {name: count for name, count in clipped.items() if count} == {}


# The firmware's table.


def test_the_firmware_table_is_the_manifest(harness: Path) -> None:
    """The generated table carries config/showcase.yaml's entries in order.

    Each learned one carries its policy's name, bound and squash, and each hardware test
    the test it runs.
    """
    yaml = pytest.importorskip("yaml")
    manifest = yaml.safe_load((ROOT / "config" / "showcase.yaml").read_text())[
        "entries"
    ]
    expected = []
    for entry in manifest:
        fields = [
            entry["title"],
            str(entry["group"]),
            str(int(entry.get("main", False))),
            str(int(entry.get("variant", False))),
            entry["kind"],
            entry.get("probe", ""),
            str(entry.get("fall_persist_cycles", 0)),
        ]
        if "policy" in entry:
            fields += [
                entry["policy"],
                f"{entry['accel_bound']:g}",
                str(int(entry["squash_actions"])),
            ]
        expected.append("|".join(fields))
    assert run(harness, "table") == expected


@pytest.mark.parametrize(
    "vectors", sorted((BOARD / "policies").glob("*.json")), ids=lambda path: path.stem
)
def test_each_table_policy_matches_its_export(harness: Path, vectors: Path) -> None:
    """The board's forward pass for every policy in the table matches PyTorch's.

    The vectors are the ones exported with it, and its command is that output bounded
    the policy's own way and scaled by its own bound.
    """
    data = json.loads(vectors.read_text())
    stdin = "".join(
        f"{data['name']} " + " ".join(f"{value:.9g}" for value in obs) + "\n"
        for obs in data["observations"]
    )
    rows = [line.split() for line in run(harness, "policies", stdin=stdin)]
    assert len(rows) == len(data["actions"])
    for (forward, command), action in zip(rows, data["actions"], strict=True):
        assert float(forward) == pytest.approx(action, abs=1e-5)
        bounded = (
            math.tanh(action) if data["squash_actions"] else max(-1.0, min(1.0, action))
        )
        assert float(command) == pytest.approx(bounded * data["accel_bound"], abs=1e-3)


@pytest.fixture(scope="module")
def exporter() -> ModuleType:
    """scripts/export_showcase.py, imported; it needs torch for the policy export."""
    pytest.importorskip("torch")
    pytest.importorskip("yaml")
    spec = importlib.util.spec_from_file_location(
        "export_showcase", ROOT / "scripts" / "export_showcase.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_generated_table_and_policies_are_current(exporter: ModuleType) -> None:
    """The committed table, headers and vectors are current, byte for byte.

    Regenerating from the manifest and its checkpoints reproduces them, and nothing else
    sits in board/policies/.
    """
    assert exporter.check(exporter.load()) == []


# The manifest's rules.

SMALL_MANIFEST = [
    {"title": "PID", "group": 1, "main": True, "kind": "stock"},
    {"title": "LQR", "group": 1, "variant": True, "kind": "stock_lqr"},
    {
        "title": "RING-DOWN",
        "group": 2,
        "main": True,
        "kind": "probe",
        "probe": "ringdown",
    },
    {"title": "FREE SWING", "group": 2, "kind": "probe", "probe": "freeswing"},
]


def load_manifest(exporter: ModuleType, tmp_path: Path, entries: list[dict]) -> list:
    """The generator's reading of a manifest with these entries."""
    import yaml

    path = tmp_path / "showcase.yaml"
    path.write_text(yaml.safe_dump({"entries": entries}, sort_keys=False))
    return exporter.load(path)


def test_a_small_manifest_with_a_variant_and_a_history_loads(
    exporter: ModuleType, tmp_path: Path
) -> None:
    """One group with a variant and one with history is a table the firmware carries."""
    entries = load_manifest(exporter, tmp_path, SMALL_MANIFEST)
    assert [(e.title, e.main, e.variant) for e in entries] == [
        ("PID", True, False),
        ("LQR", False, True),
        ("RING-DOWN", True, False),
        ("FREE SWING", False, False),
    ]
    source = exporter.table_source(entries)
    assert (
        '{"LQR", 1, 0, 1, SHOWCASE_STOCK_LQR, SHOWCASE_PROBE_NONE, NULL, 0},' in source
    )
    assert "SHOWCASE_PROBE, SHOWCASE_PROBE_RINGDOWN, NULL," in source


def edited(index: int | None = None, insert: dict | None = None, **changes) -> list:
    """SMALL_MANIFEST with `changes` to entry `index`, or with `insert` put there.

    A change to None removes that field.
    """
    entries = [dict(entry) for entry in SMALL_MANIFEST]
    if insert is not None:
        entries.insert(index, insert)
    elif index is not None:
        entries[index].update(changes)
        entries[index] = {k: v for k, v in entries[index].items() if v is not None}
    return entries


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            edited(2, insert={"title": "OLD PID", "group": 1, "kind": "stock"}),
            "has a variant and history",
        ),
        (
            edited(
                2,
                insert={"title": "LQR2", "group": 1, "variant": True, "kind": "stock"},
            ),
            "more than one variant",
        ),
        (edited(1, main=True), "exactly one main entry"),
        (edited(0, variant=True), "a variant is not a main entry"),
        (edited(0, title="PIDPIDPI"), "the limit for a main entry and its variant"),
        (
            [
                SMALL_MANIFEST[0],
                SMALL_MANIFEST[2],
                SMALL_MANIFEST[1],
                SMALL_MANIFEST[3],
            ],
            "must sit together",
        ),
        (edited(2, probe=None), "a probe entry needs probe"),
        (edited(2, probe="lean"), "a probe entry needs probe"),
        (edited(2, policy="momentum_a60d_seed1"), "only a learned entry carries"),
        (edited(1, accel_bound=60), "only a learned entry carries"),
        (edited(0, probe="tilt"), "only a probe entry names a probe"),
        (edited(3, speed=3), "unknown field speed"),
        (
            SMALL_MANIFEST
            + [
                {"title": f"MODE {k}", "group": 3 + k, "main": True, "kind": "stock"}
                for k in range(13)
            ],
            "17 entries, over SHOWCASE_MAX_ENTRIES, 16",
        ),
        (edited(3, kind="stock", probe=None), "group 2 mixes hardware tests and"),
        (edited(0, kind="probe", probe="tilt"), "group 1 mixes hardware tests and"),
        (
            edited(3, fall_persist_cycles=1500),
            "only a learned entry carries fall_persist_cycles",
        ),
        (edited(3, title="PID"), "a title is used twice"),
        (edited(3, title=""), "must be printable ASCII"),
        (edited(3, title="FREE\tSWING"), "must be printable ASCII"),
        (edited(1, main="yes"), "main must be bool"),
        (edited(3, group="2"), "group must be int"),
        (edited(3, group=True), "group must be int"),
        (edited(2, kind=None), "missing kind"),
    ],
    ids=[
        "variant-and-history",
        "two-variants",
        "variant-marked-main",
        "main-marked-variant",
        "swap-title-too-long",
        "variant-away-from-its-main",
        "probe-without-a-test",
        "probe-with-an-unknown-test",
        "probe-with-a-policy",
        "lqr-with-a-bound",
        "test-on-a-stock-entry",
        "unknown-field",
        "too-many-entries",
        "controller-behind-a-test",
        "test-beside-a-controller",
        "fall-persistence-on-stock",
        "duplicate-title",
        "empty-title",
        "tab-in-a-title",
        "main-not-bool",
        "group-not-int",
        "group-a-bool",
        "missing-kind",
    ],
)
def test_the_generator_rejects_a_table_the_carousel_cannot_carry(
    exporter: ModuleType, tmp_path: Path, entries: list[dict], message: str
) -> None:
    """Each rule on variants, probes and the stock LQR fails the load, saying why."""
    with pytest.raises(exporter.ManifestError, match=message):
        load_manifest(exporter, tmp_path, entries)

"""Tests for the showcase's probe math against the offline analyses.

The showcase's hardware tests report one measured number each: the free swing's
suspended-mode frequency, the ring-down's effective Q at its release amplitude, and the
tilt sweep's baseplate tilt. `board/showcase_probe.c` computes them on the board, a
sample at a time from running sums. These tests compile it into a host harness
(`board/test_probe.c`), replay Experiment 03's committed captures through it, and
compare with the Python analyses that produced the experiment's numbers:
`furuta.freeswing`, `furuta.pump`, and the fit in the experiment's `plot_sweep.py`.
Synthetic signals with known answers and the edge cases follow.

The compiler is the host's (tests/conftest.py). Nothing here touches the firmware
toolchain.
"""

from __future__ import annotations

import ast
import bisect
import inspect
import math
import subprocess
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from statistics import median

import numpy as np
import pytest

from furuta.freeswing import (
    LINEAR_BAND_HIGH_DEG,
    LINEAR_BAND_LOW_DEG,
    Trace,
    analyse,
    find_peaks,
    frequency_from_crossings,
    linear_band,
    read_trace,
    segment_releases,
    split_on_reexcitation,
)
from furuta.parameters import FurutaParameters
from furuta.pump import (
    RingdownSegment,
    qeff_vs_amplitude,
    read_state_trace,
    split_segments,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "board"
SOURCES = [BOARD / name for name in ("showcase_probe.c", "test_probe.c")]
EXPERIMENT = ROOT / "docs" / "experiments" / "03-hardware-bringup"
SWEEP_SCRIPT = EXPERIMENT / "figures" / "plot_sweep.py"

COUNTS_PER_REV = FurutaParameters.from_yaml().encoder_counts_per_rev
# The analyses convert with the firmware's rounded ENCODER_READ_ANGLE_SCALE.
COUNTS_PER_DEGREE = 6.666667

# What Experiment 03 reports (writeup.md, "The suspended mode" and "Where upright sits
# as the arm turns").
FREE_SWING_HZ = 1.168
TILT_DEG = 0.51

# How far apart two corrected frequencies from the same release may land, in whole
# millihertz, when fed from different datums. The correction removes the datum's effect
# on each crossing to first order; what is left is where the integer samples fall about
# zero, which can move each end crossing of the band by up to one 2 ms sample. That
# moves the band's span, three cycles or about 2.57 s, by up to 4 ms, and the frequency
# by up to 1.168 Hz x 4 ms / 2.57 s, 1.8 mHz. Rounding each estimate to a whole
# millihertz adds under 1 more, and a spread of whole millihertz under 2.8 is at most 2.
TIMING_SPREAD_MHZ = 2


@pytest.fixture(scope="module")
def harness(build_harness: Callable[..., Path]) -> Path:
    """The host harness, built with the board code's warning flags."""
    return build_harness("test_probe", SOURCES)


def run(harness: Path, mode: str, lines: list[str]) -> list[str]:
    """Feed `lines` to one harness mode and return its output lines."""
    result = subprocess.run(
        [str(harness), mode],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def swing(harness: Path, samples: list[tuple[int, int]]) -> dict:
    """The meter's report on `(t_us, counts)` samples.

    Frequencies in hertz, the datum offset in counts and Q_eff as a plain number, each
    None when the meter has none, plus the amplitude of every half swing in order.
    """
    lines = run(harness, "swing", [f"{t} {c}" for t, c in samples])
    fields = {}
    halves = []
    for line in lines:
        name, *values = line.split()
        if name == "half":
            halves.append(int(values[1]))
        else:
            fields[name] = values

    def number(name: str, scale: float) -> float | None:
        value = fields[name][0]
        return None if value == "none" else int(value) / scale

    return {
        "frequency": number("frequency", 1000.0),
        "crossing": number("crossing", 1000.0),
        "datum": number("datum", 1000.0),
        "qeff": number("qeff", 1000.0),
        "qeff_amplitude": int(fields["qeff"][1]) if fields["qeff"][0] != "none" else 0,
        "amplitude": int(fields["amplitude"][0]),
        "half_swings": int(fields["half_swings"][0]),
        "done": fields["done"][0] == "1",
        "halves": halves,
    }


def tilt(harness: Path, stops: list[tuple[float, float]]) -> tuple[float, ...] | None:
    """The fit's amplitude, bearing and offset in radians over `(arm, rest)` stops."""
    lines = run(harness, "tilt", [f"{arm!r} {rest!r}" for arm, rest in stops])
    return None if lines == ["none"] else tuple(float(v) for v in lines[0].split())


# Constants.


@pytest.fixture(scope="module")
def constants(harness: Path) -> dict[str, int]:
    """The constants and struct sizes the harness was compiled with."""
    return {
        name: int(value)
        for name, value in (line.split() for line in run(harness, "constants", []))
    }


def test_constants_match_the_analyses(constants: dict[str, int]) -> None:
    """The board's counts per revolution, band, hysteresis and Q floor are the Python's.

    The counts per revolution come from `config/edukit.yaml`, as the simulation reads
    them; the rest from `furuta.freeswing` and `furuta.pump`, in counts.
    """
    deadband = inspect.signature(frequency_from_crossings).parameters["deadband_counts"]
    assert constants["SHOWCASE_PROBE_COUNTS_PER_REV"] == COUNTS_PER_REV
    assert constants["SHOWCASE_PROBE_HYSTERESIS_COUNTS"] == deadband.default
    assert constants["SHOWCASE_PROBE_BAND_LOW_COUNTS"] == pytest.approx(
        LINEAR_BAND_LOW_DEG * COUNTS_PER_REV / 360
    )
    assert constants["SHOWCASE_PROBE_BAND_HIGH_COUNTS"] == pytest.approx(
        LINEAR_BAND_HIGH_DEG * COUNTS_PER_REV / 360
    )
    # `qeff_vs_amplitude` takes pairs starting over one degree: 7 counts and up.
    assert constants["SHOWCASE_PROBE_QEFF_MIN_COUNTS"] == math.ceil(COUNTS_PER_DEGREE)


def test_state_is_running_sums_only(constants: dict[str, int]) -> None:
    """Both structs stay small: no sample buffer has crept in.

    A buffer of even one second at the 2 ms period would be 2000 bytes.
    """
    assert constants["sizeof_swing_meter_t"] <= 128
    assert constants["sizeof_tilt_fit_t"] <= 64


# The free-swing capture.


@pytest.fixture(scope="module")
def free_swing() -> dict:
    """Experiment 03's free-swing capture, raw and split into releases.

    The releases are the ones `analyze_freeswing.py` fits: segmented, split where the
    swing grows again, and kept when they hold five cycles. Each is a start index into
    the raw samples, a length, and the Python analysis of it.
    """
    path = EXPERIMENT / "freeswing.tsv"
    times: list[int] = []
    counts: list[int] = []
    for line in path.read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 2:
            continue
        try:
            t, count = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        times.append(t)
        counts.append(count)
    whole = read_trace(path, COUNTS_PER_DEGREE)
    releases = []
    for release in split_on_reexcitation(segment_releases(whole)):
        result = analyse(release)
        if result.cycles >= 5:
            start = bisect.bisect_left(whole.time_s, release.time_s[0])
            releases.append((start, len(release), result))
    return {
        "times": times,
        "counts": counts,
        # `read_trace` measures every release from the capture's median count.
        "datum": median(counts),
        "releases": releases,
    }


def release_samples(
    capture: dict, index: int, datum: float, lead: int = 0
) -> list[tuple[int, int]]:
    """One release's samples from `datum`, starting `lead` samples early."""
    start, length, _ = capture["releases"][index]
    first = max(0, start - lead)
    return [
        (capture["times"][i], capture["counts"][i] - round(datum))
        for i in range(first, start + length)
    ]


def test_capture_holds_the_five_releases(free_swing: dict) -> None:
    """The fixture is Experiment 03's: five releases averaging 1.168 Hz.

    The capture's median, the datum `read_trace` measures from, is a whole count, so
    feeding the meter from it rounds nothing.
    """
    assert free_swing["datum"] == int(free_swing["datum"])
    frequencies = [result.frequency_hz for _, _, result in free_swing["releases"]]
    assert len(frequencies) == 5
    assert sum(frequencies) / 5 == pytest.approx(FREE_SWING_HZ, abs=5e-4)


@pytest.mark.parametrize("index", range(5))
def test_free_swing_crossings_match_the_offline_analysis(
    harness: Path, free_swing: dict, index: int
) -> None:
    """Given the same datum, the meter times the same crossings as `freeswing.analyse`.

    The meter's uncorrected estimate is the offline method run a sample at a time: the
    same hysteresis, the same interpolated crossing, the same band edges. It reports
    whole millihertz, so the same crossings put it within half a millihertz of the
    Python; a crossing or a half swing gained or lost at a band edge moves a three-cycle
    estimate by 2 millihertz or more.
    """
    _, _, result = free_swing["releases"][index]
    got = swing(harness, release_samples(free_swing, index, free_swing["datum"]))

    assert got["crossing"] is not None
    assert got["crossing"] == pytest.approx(result.frequency_hz, abs=0.5005e-3)
    assert got["done"]


@pytest.mark.parametrize("index", range(5))
def test_free_swing_frequency_reproduces_experiment_03(
    harness: Path, free_swing: dict, index: int
) -> None:
    """The datum-corrected frequency is the offline one to within its datum sensitivity.

    The analysis's estimate moves in steps of 2 to 2.5 millihertz per count of datum:
    the band is three cycles, and its last crossings are at 3 degrees, where one count
    is 5 percent of the swing. The meter's correction moves each release's datum by
    under a count here, asserted, so it may land up to one such step from the Python's
    on any one release.
    """
    _, _, result = free_swing["releases"][index]
    got = swing(harness, release_samples(free_swing, index, free_swing["datum"]))

    assert got["datum"] is not None
    assert abs(got["datum"]) < 1.0
    assert got["frequency"] == pytest.approx(result.frequency_hz, abs=2.5e-3)


def test_free_swing_mean_is_experiment_03s(harness: Path, free_swing: dict) -> None:
    """Over the five releases the meter's mean is the reported 1.168 Hz.

    Independent errors of up to 2.5 millihertz per release average down to about 1 over
    five; the display shows whole millihertz.
    """
    frequencies = [
        swing(harness, release_samples(free_swing, index, free_swing["datum"]))[
            "frequency"
        ]
        for index in range(5)
    ]
    assert sum(frequencies) / 5 == pytest.approx(FREE_SWING_HZ, abs=1e-3)


@pytest.mark.parametrize("index", range(5))
def test_free_swing_frequency_does_not_depend_on_the_datum(
    harness: Path, free_swing: dict, index: int
) -> None:
    """Off by up to two counts, the datum moves the corrected estimate by 2 mHz at most.

    Two counts is the spread dry friction leaves in where the pendulum comes to rest,
    which is where the firmware takes its datum. The uncorrected estimate moves by
    several times that over the same offsets, which is what the correction is for; the
    assertion on it keeps the offsets large enough to show it. What remains in the
    corrected one is the crossings' own timing, bounded by `TIMING_SPREAD_MHZ`.
    """
    base = free_swing["datum"]
    runs = [
        swing(harness, release_samples(free_swing, index, base + offset))
        for offset in (-2, -1, 0, 1, 2)
    ]
    corrected = [round(r["frequency"] * 1000) for r in runs]
    uncorrected = [r["crossing"] for r in runs]

    assert max(corrected) - min(corrected) <= TIMING_SPREAD_MHZ
    assert max(uncorrected) - min(uncorrected) >= 4e-3
    for offset, r in zip((-2, -1, 0, 1, 2), runs, strict=True):
        assert r["datum"] == pytest.approx(runs[2]["datum"] - offset, abs=0.1)


@pytest.mark.parametrize("index", range(5))
def test_free_swing_from_rest_as_the_firmware_feeds_it(
    harness: Path, free_swing: dict, index: int
) -> None:
    """Fed from two seconds before the release, from the rest before it, same answer.

    The firmware starts the meter with the pendulum hanging, takes its datum from the
    rest angle, and a hand lifts and releases the pendulum. The lead-in holds the rest,
    the lift, and on some releases the tail of the one before, none of which may reach
    the result. The datum differs from the reference's, so the two agree to within
    `TIMING_SPREAD_MHZ`.
    """
    lead = 1000
    start, _, _ = free_swing["releases"][index]
    before = free_swing["counts"][max(0, start - lead) : max(0, start - lead) + 500]
    reference = swing(harness, release_samples(free_swing, index, free_swing["datum"]))

    got = swing(harness, release_samples(free_swing, index, median(before), lead))

    assert got["done"]
    spread = abs(round(got["frequency"] * 1000) - round(reference["frequency"] * 1000))
    assert spread <= TIMING_SPREAD_MHZ


# The ring-down capture.


@pytest.fixture(scope="module")
def ring_downs() -> list[tuple[list[tuple[int, int]], object]]:
    """Each held decay of Experiment 03's ring-down capture, raw and as `pump` cuts it.

    The raw decays are the runs of H lines. A pump that never moved the pendulum leaves
    a decay with no swing in it, which `split_segments` drops, so it is dropped here
    too before the two are paired in order.
    """
    path = EXPERIMENT / "pump.tsv"
    raw: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] | None = None
    for line in path.read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            continue
        try:
            sample = (int(fields[1]), int(fields[2]))
        except ValueError:
            continue
        state = fields[4].strip()
        if state == "H":
            if current is None:
                current = []
                raw.append(current)
            current.append(sample)
        elif state == "P":
            current = None
    moving = [decay for decay in raw if len({c for _, c in decay}) > 1]
    trace, states = read_state_trace(path, COUNTS_PER_DEGREE)
    segments = split_segments(trace, states)
    assert len(moving) == len(segments) == 6
    return list(zip(moving, segments, strict=True))


def from_datum(decay: list[tuple[int, int]], datum: int) -> list[tuple[int, int]]:
    """A decay's samples measured from `datum`."""
    return [(t, c - datum) for t, c in decay]


@pytest.mark.parametrize("index", range(6))
def test_ringdown_qeff_matches_the_offline_analysis(
    harness: Path, ring_downs: list, index: int
) -> None:
    """Q_eff at the release amplitude is `qeff_vs_amplitude`'s for the same pair.

    `pump` measures each decay from its own median, which is where the meter is fed
    from, rounded to a count. The release amplitude is the decay's largest turning
    point, `target_amplitude_deg`, and every half swing the meter reports is one of
    the Python's turning points. The Python pair is the one ending on the same peak as
    the meter's.

    Tolerance: 1 percent on Q. Near vertical the pendulum lingers at the top, and the
    Python can start its pair on a dither sample a few counts under the highest one,
    where the meter takes the highest; on the 165 degree decay that is 3 counts and
    moves Q by 0.5 percent. Rounding the datum moves Q by under 0.1 percent. Pairing
    peaks from opposite sides or a cycle apart, the errors this guards against, move
    it by tens of percent.
    """
    decay, segment = ring_downs[index]
    datum = median(c for _, c in decay)
    got = swing(harness, from_datum(decay, round(datum)))

    half_count = 0.5 + 1e-6
    turning_points = [
        p.amplitude_deg * COUNTS_PER_DEGREE for p in find_peaks(segment.trace)
    ]
    for amplitude in got["halves"][:6]:
        assert min(abs(amplitude - p) for p in turning_points) <= half_count

    high, low = got["halves"][0], got["halves"][2]
    assert got["qeff_amplitude"] == high
    assert high == pytest.approx(
        segment.target_amplitude_deg * COUNTS_PER_DEGREE, abs=half_count
    )
    assert got["qeff"] == pytest.approx(math.pi * high / (high - low), abs=1e-3)

    pairs = [
        (h, q)
        for h, q in qeff_vs_amplitude(segment)
        if abs(h * (1.0 - math.pi / q) * COUNTS_PER_DEGREE - low) <= half_count
    ]
    assert len(pairs) == 1
    assert got["qeff"] == pytest.approx(pairs[0][1], rel=0.01)


@pytest.mark.parametrize("index", range(6))
def test_ringdown_crossings_match_the_offline_analysis(
    harness: Path, ring_downs: list, index: int
) -> None:
    """On each decay the uncorrected frequency is `freeswing.analyse`'s at the datum.

    The decay is measured from its median rounded down to a count on both sides, so
    the two see the same samples. As for the free swing: within half a millihertz.
    """
    decay, _ = ring_downs[index]
    datum = math.floor(median(c for _, c in decay))
    trace = Trace(
        tuple(t / 1e6 for t, _ in decay),
        tuple((c - datum) / COUNTS_PER_DEGREE for _, c in decay),
        COUNTS_PER_DEGREE,
    )
    result = analyse(trace)

    got = swing(harness, from_datum(decay, datum))

    assert result.band_cycles >= 1
    assert got["crossing"] == pytest.approx(result.frequency_hz, abs=0.5005e-3)


def test_ringdown_frequency_agrees_with_the_free_swing(
    harness: Path, ring_downs: list
) -> None:
    """Corrected, every decay's frequency is the free swing's; uncorrected, not so.

    A decay's median is not its center: the large decays' own peaks put the center up
    to 6.5 counts off it, and with only one cycle in the band that moves the offline
    estimate by up to 2 percent. The corrected estimates land within 0.3 percent of the
    free swing's 1.168 Hz. That is Experiment 03's agreement between the two modes,
    0.2 percent, with a count's timing to spare.
    """
    corrected, uncorrected = [], []
    for decay, _ in ring_downs:
        got = swing(harness, from_datum(decay, round(median(c for _, c in decay))))
        corrected.append(got["frequency"])
        uncorrected.append(got["crossing"])

    assert all(f == pytest.approx(FREE_SWING_HZ, rel=3e-3) for f in corrected)
    assert max(abs(f - FREE_SWING_HZ) for f in uncorrected) > 0.01


# The tilt sweep capture.


@pytest.fixture(scope="module")
def sweep_script() -> dict:
    """`read_dwells` and `fit_sinusoid` from Experiment 03's `plot_sweep.py`.

    The script imports matplotlib at the top, which the tests do without, so the two
    functions and the constant they read are compiled out of its parsed source rather
    than imported.
    """
    tree = ast.parse(SWEEP_SCRIPT.read_text())
    wanted = {"read_dwells", "fit_sinusoid", "COUNTS_PER_DEGREE"}
    body = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in wanted)
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in wanted for t in node.targets)
        )
    ]
    namespace = {"np": np, "median": median, "defaultdict": defaultdict, "Path": Path}
    module = ast.Module(body=body, type_ignores=[])
    exec(compile(module, str(SWEEP_SCRIPT), "exec"), namespace)
    assert wanted <= namespace.keys()
    return namespace


@pytest.fixture(scope="module")
def dwell_rests() -> list[tuple[int, float]]:
    """One resting angle per stop, in degrees, as `plot_sweep.py` takes it.

    Each stop's rest is the median count after its first 500 samples, the first second
    of the dwell. The script pools every run's samples at an arm angle into one median;
    the firmware makes one pass and sees one stop at a time, so this takes each stop on
    its own. A dwell starts where the timestamp restarts.
    """
    dwells: list[tuple[int, list[int]]] = []
    previous = None
    for line in (EXPERIMENT / "sweep.tsv").read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        try:
            t, count, arm = (int(f) for f in fields)
        except ValueError:
            continue
        if previous is None or t < previous:
            dwells.append((arm, []))
        dwells[-1][1].append(count)
        previous = t
    assert len(dwells) == 42
    return [(arm, median(counts[500:]) / COUNTS_PER_DEGREE) for arm, counts in dwells]


def fit_in_degrees(
    harness: Path, arms: list[float], rests: list[float]
) -> tuple[float, ...] | None:
    """The C fit over stops given in degrees, returned in degrees."""
    stops = [
        (math.radians(a), math.radians(r)) for a, r in zip(arms, rests, strict=True)
    ]
    fit = tilt(harness, stops)
    return None if fit is None else tuple(math.degrees(v) for v in fit)


# The inputs are about 0.5 degrees and float32 carries them to a few 1e-8 degrees, so
# the fit's round-off sits orders under these. A wrong normal equation is off by the
# size of the tilt.
AMPLITUDE_TOL_DEG = 1e-5
BEARING_TOL_DEG = 1e-3


def test_tilt_fit_reproduces_experiment_03(harness: Path, sweep_script: dict) -> None:
    """On the script's own pooled rest angles, the fit is the script's: 0.51 degrees."""
    dwells = sweep_script["read_dwells"](EXPERIMENT / "sweep.tsv")
    arms, rests = list(dwells), list(dwells.values())
    amplitude, bearing, offset = sweep_script["fit_sinusoid"](arms, rests)

    got = fit_in_degrees(harness, arms, rests)

    assert round(amplitude, 2) == TILT_DEG
    assert got[0] == pytest.approx(amplitude, abs=AMPLITUDE_TOL_DEG)
    assert got[1] == pytest.approx(bearing, abs=BEARING_TOL_DEG)
    assert got[2] == pytest.approx(offset, abs=AMPLITUDE_TOL_DEG)


@pytest.mark.parametrize("stops", ["all", "pass 1", "pass 2", "pass 3"])
def test_tilt_fit_on_one_rest_per_stop(
    harness: Path, sweep_script: dict, dwell_rests: list, stops: str
) -> None:
    """One rest per stop, as the firmware collects them: the numpy fit, and 0.51.

    Each pass is 14 stops, 0 to 360 degrees and back to 0. The C fit matches the
    script's least squares to round-off. Against Experiment 03's 0.51 the tolerance is
    three standard errors of the amplitude, from the fit's own residuals: sigma times
    root(2 / n) for stops spread round the circle. Each stop's rest angle is the
    median of a pendulum still ringing from the move, 0.06 to 0.09 degrees rms about
    the fit, so a single pass reads 0.43 to 0.52.
    """
    chosen = {
        "all": dwell_rests,
        "pass 1": dwell_rests[0:14],
        "pass 2": dwell_rests[14:28],
        "pass 3": dwell_rests[28:42],
    }[stops]
    arms = [arm for arm, _ in chosen]
    rests = [rest for _, rest in chosen]
    amplitude, bearing, offset = sweep_script["fit_sinusoid"](arms, rests)

    got = fit_in_degrees(harness, arms, rests)

    assert got[0] == pytest.approx(amplitude, abs=AMPLITUDE_TOL_DEG)
    assert got[1] == pytest.approx(bearing, abs=BEARING_TOL_DEG)
    assert got[2] == pytest.approx(offset, abs=AMPLITUDE_TOL_DEG)

    phi = np.radians(arms)
    model = amplitude * np.sin(phi - math.radians(bearing)) + offset
    residuals = np.array(rests) - model
    sigma = math.sqrt(float(np.sum(residuals**2)) / (len(rests) - 3))
    standard_error = sigma * math.sqrt(2.0 / len(rests))
    assert got[0] == pytest.approx(TILT_DEG, abs=3.0 * standard_error)


# Synthetic swings.


def decay(
    frequency_hz: float,
    quality: float,
    amplitude: float,
    *,
    offset: float = 0.0,
    seconds: float = 30.0,
    peak_s: float = 0.1,
    t0_us: int = 1_000_000,
    dt_us: int = 2000,
) -> list[tuple[int, int]]:
    """A viscous ring-down, quantized to counts, sampled every `dt_us`.

    The first peak comes `peak_s` after the first sample, so the meter sees the swing
    rise into it, as it does after a release. `offset` is a datum error in counts: the
    swing is centered there rather than on zero. Timestamps wrap at 32 bits, as the
    firmware's do.
    """
    tau = quality / (math.pi * frequency_hz)
    samples = []
    for k in range(int(seconds * 1e6 / dt_us)):
        t = k * dt_us / 1e6 - peak_s
        x = amplitude * math.exp(-t / tau) * math.cos(2.0 * math.pi * frequency_hz * t)
        samples.append(((t0_us + k * dt_us) % 2**32, round(x + offset)))
    return samples


def viscous_qeff(quality: float, amplitude: float, offset: float = 0.0) -> float:
    """The Q_eff a pure viscous decay of quality factor Q reads as, from `offset` off.

    Same-side peaks a cycle apart have the ratio r = exp(-pi / Q). From a datum
    `offset` off they read A + offset and A r + offset, so the fraction lost is
    A (1 - r) / (A + offset) and Q_eff = pi (A + offset) / (A (1 - r)). With no offset
    that is about Q + pi / 2: Q_eff is defined by the fraction lost, which is pi / Q
    only to first order.
    """
    loss = amplitude * (1.0 - math.exp(-math.pi / quality)) / (amplitude + offset)
    return math.pi / loss


# A 1.2 Hz swing released from 90 degrees at Q 12. The band then lasts about five
# seconds, a dozen half periods, twice the real pendulum's but short enough that a datum
# error shows in the crossings; and the release pair is 138 counts apart, so one count
# of quantization is under 1 percent of Q_eff.
SYNTHETIC = {"frequency_hz": 1.2, "quality": 12.0, "amplitude": 600.0}


@pytest.mark.parametrize("offset", [0.0, 2.4, -3.0])
def test_synthetic_decay_reads_its_frequency_and_q(
    harness: Path, offset: float
) -> None:
    """A ring-down with known frequency and Q, measured from a datum `offset` off.

    Frequency: within 1.5 millihertz. The zero crossings of a viscous decay are exactly
    periodic, but the timing rule, shared with freeswing.py, puts each crossing at the
    last sample reading zero, half a count past it: 3 ms late at the band's 3 degree
    end and under 1 ms at its top, against a five-second span. Uncorrected, 2.4 counts
    of datum error moves the estimate by more than 3 millihertz. The datum comes back
    to within 0.4 counts: the three-peak estimate is exact for dry friction but carries
    A v^2 / 4 for a viscous loss v per half swing, 0.4 counts at the band's top at
    Q 12, alternating in sign from one triple to the next.

    Q_eff: the release pair is quantized to a count at each end, which bounds its error
    at Q_eff times (1 / (high - low) + 0.5 / high).
    """
    got = swing(harness, decay(**SYNTHETIC, offset=offset))

    assert got["done"]
    assert got["frequency"] == pytest.approx(SYNTHETIC["frequency_hz"], abs=1.5e-3)
    assert got["datum"] == pytest.approx(offset, abs=0.4)
    if abs(offset) >= 2.4:
        assert abs(got["crossing"] - SYNTHETIC["frequency_hz"]) > 3e-3

    amplitude, quality = SYNTHETIC["amplitude"], SYNTHETIC["quality"]
    expected = viscous_qeff(quality, amplitude, offset)
    high = amplitude + offset
    low = amplitude * math.exp(-math.pi / quality) + offset
    bound = expected * (1.0 / (high - low) + 0.5 / high)
    assert got["qeff_amplitude"] == pytest.approx(high, abs=1.5)
    assert got["qeff"] == pytest.approx(expected, abs=bound)


def test_timestamps_may_wrap(harness: Path) -> None:
    """A decay whose microsecond clock wraps partway reads as one that does not."""
    plain = decay(**SYNTHETIC)
    wrapped = decay(**SYNTHETIC, t0_us=2**32 - 5_000_000)

    assert run(harness, "swing", [f"{t} {c}" for t, c in wrapped]) == run(
        harness, "swing", [f"{t} {c}" for t, c in plain]
    )


def test_uneven_sampling_reads_the_same_frequency(harness: Path) -> None:
    """Samples 2.2 ms apart read the same frequency: the timing is by timestamp."""
    got = swing(harness, decay(**SYNTHETIC, dt_us=2200))
    assert got["frequency"] == pytest.approx(1.2, abs=1.5e-3)


# Edge cases.


def test_no_samples_reads_nothing(harness: Path) -> None:
    """With nothing fed in, there is no result and no half swing."""
    for samples in ([], [(0, 5)]):
        got = swing(harness, samples)
        assert got["frequency"] is None
        assert got["crossing"] is None
        assert got["datum"] is None
        assert got["qeff"] is None
        assert got["amplitude"] == 0
        assert got["half_swings"] == 0
        assert not got["done"]


@pytest.mark.parametrize(("dither", "counted"), [(1, False), (2, False), (3, True)])
def test_hysteresis_ignores_dither_at_rest(
    harness: Path, dither: int, counted: bool
) -> None:
    """A pendulum dithering two counts either side of hanging never completes a swing.

    Three counts is past the hysteresis, so there the flips count, though as swings too
    small to have a turning point.
    """
    samples = [(k * 2000, dither if k % 3 == 0 else -dither) for k in range(2000)]
    got = swing(harness, samples)

    assert (got["half_swings"] > 0) is counted
    assert got["frequency"] is None
    assert got["qeff"] is None


def steady(amplitude: float, seconds: float = 20.0) -> list[tuple[int, int]]:
    """An undamped 1.2 Hz swing, rising into its first peak."""
    return decay(1.2, 1e12, amplitude, seconds=seconds)


@pytest.mark.parametrize("amplitude", [200.0, 13.0])
def test_a_swing_that_never_enters_the_band_has_no_frequency(
    harness: Path, amplitude: float
) -> None:
    """A steady 30 degree swing is above the band, a steady 2 degree one below it.

    Neither loses amplitude, so neither has a Q_eff either.
    """
    got = swing(harness, steady(amplitude))

    assert got["half_swings"] > 40
    assert got["amplitude"] == pytest.approx(amplitude, abs=1.0)
    assert got["frequency"] is None
    assert got["qeff"] is None
    assert not got["done"]


def test_a_decay_cut_off_above_the_band_has_q_but_no_frequency(harness: Path) -> None:
    """Released at 60 degrees and stopped at 25: Q_eff at release, and no frequency."""
    samples = decay(1.2, 25.0, 400.0, seconds=6.0)
    got = swing(harness, samples)

    assert got["amplitude"] > 150
    assert got["frequency"] is None
    assert got["qeff"] == pytest.approx(viscous_qeff(25.0, 400.0), rel=0.03)
    assert got["qeff_amplitude"] == pytest.approx(400, abs=1)


def test_a_decay_too_fast_for_the_band_has_no_frequency(harness: Path) -> None:
    """At Q 1.5 the swing falls through the whole band in under one cycle."""
    got = swing(harness, decay(1.2, 1.5, 150.0, seconds=6.0))

    assert got["half_swings"] >= 3
    assert got["frequency"] is None
    assert got["done"]


def test_a_swing_already_falling_has_no_release_peak(harness: Path) -> None:
    """Started just after a peak, the first half swing has no turning point in view.

    Its amplitude reads 0 and Q_eff comes from the first peak the meter saw form.
    """
    samples = decay(**SYNTHETIC, peak_s=-0.05)
    got = swing(harness, samples)

    assert got["halves"][0] == 0
    assert got["qeff_amplitude"] == got["halves"][1]
    assert got["frequency"] == pytest.approx(1.2, abs=1.5e-3)


def pushed(
    first_hz: float, second_hz: float, half_periods: int
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """A 150 count swing at `first_hz`, pushed back up to 150 as it crosses hanging.

    The first swing decays into the band for `half_periods` half periods; at that
    crossing the second, at `second_hz`, starts from zero moving the same way, so the
    motion is continuous. Returns the whole trace and the second swing alone.
    """
    tau = 12.0 / math.pi
    switch = half_periods / (2.0 * first_hz)
    direction = -1.0 if half_periods % 2 else 1.0
    whole, second = [], []
    for k in range(int(30.0 / 0.002)):
        t = k * 0.002
        if t < switch:
            x = 150.0 * math.exp(-t / tau) * math.sin(2.0 * math.pi * first_hz * t)
        else:
            since = t - switch
            envelope = direction * 150.0 * math.exp(-since / tau)
            x = envelope * math.sin(2.0 * math.pi * second_hz * since)
        sample = (1_000_000 + k * 2000, round(x))
        whole.append(sample)
        if t >= switch:
            second.append(sample)
    return whole, second


def test_a_new_release_restarts_the_band(harness: Path) -> None:
    """A swing pushed back above the band before it left restarts the timing.

    The first release, at 1.2 Hz, is inside the band when it is pushed; the second, at
    1.1 Hz, is what the meter reports, exactly as if it had been fed alone.
    """
    whole, second = pushed(1.2, 1.1, half_periods=17)
    first = swing(harness, whole[: len(whole) - len(second)])
    alone = swing(harness, second)

    got = swing(harness, whole)

    assert first["frequency"] == pytest.approx(1.2, abs=1.5e-3)
    assert not first["done"], "the first swing was still inside the band"
    assert got["frequency"] == pytest.approx(1.1, abs=1.5e-3)
    assert got["frequency"] == alone["frequency"]
    assert got["datum"] == alone["datum"]


# Edges shared with the offline analyses, on swings built to land on them.


def lobes(
    amplitudes: list[int], samples_per_lobe: list[int] | None = None
) -> list[tuple[int, int]]:
    """Half-sine lobes of alternating sign, one per amplitude, then a second of rest.

    Each lobe starts and ends on zero and its middle sample is exactly its amplitude, so
    every half swing peaks on a chosen count and every crossing falls on a sample. Lobe
    lengths are in 2 ms samples, 214 (a 1.168 Hz half period) unless given.
    """
    lengths = samples_per_lobe or [214] * len(amplitudes)
    counts = [0]
    for k, (amplitude, n) in enumerate(zip(amplitudes, lengths, strict=True)):
        sign = 1 if k % 2 == 0 else -1
        counts += [
            round(sign * amplitude * math.sin(math.pi * j / n)) for j in range(1, n)
        ]
        counts.append(0)
    counts += [0] * 500
    return [(1_000_000 + 2000 * k, c) for k, c in enumerate(counts)]


def as_trace(samples: list[tuple[int, int]]) -> Trace:
    """Samples in counts as the offline analyses read them, in seconds and degrees."""
    return Trace(
        tuple(t / 1e6 for t, _ in samples),
        tuple(c / COUNTS_PER_DEGREE for _, c in samples),
        COUNTS_PER_DEGREE,
    )


# A decay through the band with a half swing peaking on each edge: exactly 100 counts,
# 15 degrees and inside, and exactly 20, 3 degrees and outside. The half swings next to
# the edges, 88 and 20 counts, are 11 percent short, so a crossing gained or lost at
# either edge moves the estimate.
EDGE_AMPLITUDES = [150, 125, 100, 88, 76, 66, 57, 49, 42, 36, 31, 27, 23, 20, 17, 14]
EDGE_LENGTHS = [190 if a in (88, 20) else 214 for a in EDGE_AMPLITUDES]


def peak_time(k: int) -> float:
    """When lobe `k` of the edge decay peaks, in seconds."""
    return (1_000_000 + 2000 * (sum(EDGE_LENGTHS[:k]) + EDGE_LENGTHS[k] // 2)) / 1e6


def between(trace: Trace, start_s: float, end_s: float) -> Trace:
    """The part of a trace from `start_s` to `end_s`, inclusive."""
    kept = [i for i, t in enumerate(trace.time_s) if start_s <= t <= end_s]
    return Trace(
        tuple(trace.time_s[i] for i in kept),
        tuple(trace.angle_deg[i] for i in kept),
        trace.counts_per_degree,
    )


def test_band_edges_time_the_same_crossings_as_the_offline_analysis(
    harness: Path,
) -> None:
    """A 100 count peak opens the band and a 20 count peak closes it, in both.

    freeswing.py converts with the rounded 6.666667 counts per degree, so 100 counts is
    a hair under 15 degrees, inside, and 20 a hair under 3, the band's end. The meter's
    uncorrected estimate matches `frequency_from_crossings` over `linear_band` to half a
    millihertz. Timing one crossing more, past the 20 count peak, or one fewer, from
    after the 100 count one, moves that estimate by more than 10 millihertz.
    """
    samples = lobes(EDGE_AMPLITUDES, EDGE_LENGTHS)
    trace = as_trace(samples)
    band = linear_band(trace)
    expected, _ = frequency_from_crossings(band)
    one_more, _ = frequency_from_crossings(
        between(trace, band.time_s[0], peak_time(EDGE_AMPLITUDES.index(17)))
    )
    one_fewer, _ = frequency_from_crossings(
        between(trace, peak_time(EDGE_AMPLITUDES.index(88)), band.time_s[-1])
    )

    got = swing(harness, samples)

    assert got["halves"][: len(EDGE_AMPLITUDES) - 1] == EDGE_AMPLITUDES[:-1]
    assert got["crossing"] == pytest.approx(expected, abs=0.5005e-3)
    assert got["done"]
    assert abs(one_more - expected) > 10e-3
    assert abs(one_fewer - expected) > 10e-3


def test_a_peak_of_3_degrees_does_not_open_the_band(harness: Path) -> None:
    """A swing that falls from above the band straight to 20 counts never opens it.

    Twenty counts is not inside the band, so the meter never starts timing and never
    reports itself done: it has no frequency to finish. The analysis has none either.
    """
    samples = lobes([150, 125, 20, 17, 14, 12])
    python, _ = frequency_from_crossings(linear_band(as_trace(samples)))

    got = swing(harness, samples)

    assert python == 0.0
    assert got["halves"][:4] == [150, 125, 20, 17]
    assert got["frequency"] is None
    assert not got["done"]


@pytest.mark.parametrize("levels", [(2, -3), (-2, 3)])
def test_hysteresis_is_strict_on_either_side(
    harness: Path, levels: tuple[int, int]
) -> None:
    """A signal sitting at 2 counts on one side and 3 on the other completes no swing.

    Two counts is the hysteresis itself, which a side needs to exceed, as
    `frequency_from_crossings` requires; so only the 3 count side is ever confirmed and
    no crossing is timed, in either the meter or the analysis.
    """
    samples = [(2000 * k, levels[(k // 50) % 2]) for k in range(2000)]
    python, cycles = frequency_from_crossings(as_trace(samples))

    got = swing(harness, samples)

    assert (python, cycles) == (0.0, 0)
    assert got["half_swings"] == 0


@pytest.mark.parametrize(("start", "has_q"), [(6, False), (7, True)])
def test_qeff_needs_a_pair_starting_over_one_degree(
    harness: Path, start: int, has_q: bool
) -> None:
    """A same-side pair from 6 counts gives no Q_eff; one from 7 counts does.

    `qeff_vs_amplitude` takes pairs whose first peak is over one degree, 6.67 counts.
    From 7 counts the two agree on the pair and its Q_eff.
    """
    samples = lobes([start, start - 1, start - 1, start - 2])
    pairs = qeff_vs_amplitude(
        RingdownSegment(start / COUNTS_PER_DEGREE, as_trace(samples))
    )

    got = swing(harness, samples)

    assert got["halves"][:3] == [start, start - 1, start - 1]
    if has_q:
        high, quality = max(pairs)
        assert high * COUNTS_PER_DEGREE == pytest.approx(start)
        assert got["qeff_amplitude"] == start
        assert got["qeff"] == pytest.approx(quality, abs=1e-3)
    else:
        assert pairs == ()
        assert got["qeff"] is None


def test_datum_triples_come_from_inside_the_band_only(harness: Path) -> None:
    """Peaks above the band never reach the datum estimate.

    Inside the band this swing loses exactly 5 counts per half swing, so every triple
    there reads the datum as exactly zero. Above it the swing falls 100 counts in one
    half swing, and a triple reaching back to 200 would read the datum 24 counts out.
    """
    amplitudes = [300, 200, 100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30]
    amplitudes += [25, 20, 15]

    got = swing(harness, lobes(amplitudes))

    assert got["datum"] == 0.0


# Tilt fit, synthetic.


@pytest.mark.parametrize("bearing", [0.0, 1.8, -2.9, math.pi])
@pytest.mark.parametrize("stops_deg", [range(0, 361, 30), range(-180, 181, 60)])
def test_tilt_fit_recovers_a_known_sinusoid(
    harness: Path, bearing: float, stops_deg: range
) -> None:
    """Noise-free stops give back the amplitude, bearing and offset they were made from.

    Two stop patterns: the stock sweep's full turn in 30 degree steps, and a turn
    either side of home in 60 degree steps. A bearing of pi comes back as pi or -pi.
    """
    amplitude, offset = math.radians(0.51), math.radians(0.3)
    stops = [
        (math.radians(a), amplitude * math.sin(math.radians(a) - bearing) + offset)
        for a in stops_deg
    ]

    got = tilt(harness, stops)

    assert got is not None
    assert got[0] == pytest.approx(amplitude, rel=1e-4)
    wrapped = math.remainder(got[1] - bearing, 2.0 * math.pi)
    assert wrapped == pytest.approx(0.0, abs=1e-3)
    assert got[2] == pytest.approx(offset, abs=1e-7)


@pytest.mark.parametrize(
    "arms_deg",
    [[], [0.0], [0.0, 90.0], [45.0] * 5, [0.0, 180.0] * 3, [10.0, 10.5, 11.0]],
    ids=["none", "one", "two", "one angle", "two angles", "bunched"],
)
def test_tilt_fit_refuses_stops_that_cannot_fix_a_sinusoid(
    harness: Path, arms_deg: list[float]
) -> None:
    """Under three stops, or under three distinct arm angles, or all within a degree."""
    stops = [(math.radians(a), 0.001 * i) for i, a in enumerate(arms_deg)]
    assert tilt(harness, stops) is None

"""Tests for the ring-down analysis of mode d captures.

Synthetic captures carry a known viscous Q and a known Coulomb bite in the five-column
format mode d emits, exercising the reader through to the fit. The quality tests assert
the recovered Q against the value the trace was built with. The rest cover the reader,
the segmenter, the closed-form model and the counts-per-revolution read.
"""

from __future__ import annotations

import math

import pytest

from furuta.pump import (
    counts_per_rev,
    model_quality,
    qeff_vs_amplitude,
    read_state_trace,
    split_segments,
    sweep,
)

SAMPLE_RATE_HZ = 500.0
COUNTS_PER_DEGREE = 6.666667
FREQUENCY_HZ = 1.17


def _decay_counts(
    frequency_hz: float,
    tau_s: float,
    amplitude_deg: float,
    duration_s: float,
    rest_counts: int,
) -> list[int]:
    """One viscously damped decay, in raw encoder counts about a rest offset."""
    out = []
    steps = int(duration_s * SAMPLE_RATE_HZ)
    for index in range(steps):
        t = index / SAMPLE_RATE_HZ
        angle = (
            amplitude_deg
            * math.exp(-t / tau_s)
            * math.cos(2 * math.pi * frequency_hz * t)
        )
        out.append(round(angle * COUNTS_PER_DEGREE) + rest_counts)
    return out


def _write_capture(path, decays, rest_counts=1000) -> None:
    """Write a mode d capture: a short pump (P) before each decay (H)."""
    lines = ["seq\tus\tcounts\tphi\tstate"]
    seq = 0
    us = 0
    for amplitude in decays:
        # Each decay needs a P ahead of it for the segmenter to split on.
        for _ in range(6):
            lines.append(f"{seq}\t{us}\t{rest_counts}\t100\tP")
            seq += 1
            us += 2000
        counts = _decay_counts(FREQUENCY_HZ, 6.0, amplitude, 6.0, rest_counts)
        for c in counts:
            lines.append(f"{seq}\t{us}\t{c}\t0\tH")
            seq += 1
            us += 2000
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.unit
def test_reader_keeps_only_valid_five_column_lines(tmp_path) -> None:
    """Only the five-column P/H sample lines survive the reader."""
    path = tmp_path / "pump.tsv"
    _write_capture(path, [30.0])
    trace, states = read_state_trace(path, COUNTS_PER_DEGREE)
    assert len(trace.time_s) == len(states)
    assert set(states) <= {"P", "H"}
    assert "H" in states and "P" in states


@pytest.mark.unit
def test_segments_split_on_the_drive_state(tmp_path) -> None:
    """Three pumped decays split to three segments, target amplitudes descending."""
    path = tmp_path / "pump.tsv"
    _write_capture(path, [40.0, 30.0, 20.0])
    trace, states = read_state_trace(path, COUNTS_PER_DEGREE)
    segments = split_segments(trace, states)
    assert len(segments) == 3
    targets = [s.target_amplitude_deg for s in segments]
    assert targets[0] > targets[1] > targets[2]
    assert targets[0] == pytest.approx(40.0, abs=3.0)


@pytest.mark.unit
def test_viscous_quality_recovered(tmp_path) -> None:
    """A synthetic tau 6 s decay at 1.17 Hz recovers Q = pi f tau, about 22."""
    expected_q = math.pi * FREQUENCY_HZ * 6.0
    path = tmp_path / "pump.tsv"
    _write_capture(path, [25.0])
    measured = sweep(path, COUNTS_PER_DEGREE)
    assert len(measured) == 1
    assert measured[0].quality == pytest.approx(expected_q, rel=0.15)
    # A purely viscous synthetic decay has no Coulomb bite.
    assert measured[0].coulomb_deg == pytest.approx(0.0, abs=0.3)


@pytest.mark.unit
def test_qeff_recovers_the_viscous_quality(tmp_path) -> None:
    """qeff_vs_amplitude reads Q = pi f tau off same-side peaks.

    A pure-viscous decay holds a constant quality factor Q = pi f tau. Each same-side
    peak pair sits one full cycle apart and loses pi / Q of its amplitude, making the
    reading pi / loss. An earlier bug used 2 pi / loss and reported about 44, double the
    truth and above the plant's own viscous Q. Coulomb loss can only pull a reading
    below that.
    """
    expected_q = math.pi * FREQUENCY_HZ * 6.0  # tau = 6 s, so Q about 22
    path = tmp_path / "pump.tsv"
    _write_capture(path, [40.0])
    trace, states = read_state_trace(path, COUNTS_PER_DEGREE)
    segment = split_segments(trace, states)[0]
    pairs = qeff_vs_amplitude(segment)
    assert pairs
    # Mid-amplitude pairs, away from the quantized tail, read the constant viscous Q.
    mids = sorted(q for amp, q in pairs if 10.0 < amp < 35.0)
    assert mids
    assert mids[len(mids) // 2] == pytest.approx(expected_q, rel=0.15)


@pytest.mark.unit
def test_model_quality_tends_to_viscous_at_large_amplitude() -> None:
    """No Coulomb term holds Q flat at the viscous value; a bite pulls it down."""
    assert model_quality(90.0, 24.0, 0.0) == pytest.approx(24.0)
    # The bite costs a larger fraction as the swing shrinks. That amplitude dependence
    # is what the simulation must reproduce.
    q_large = model_quality(120.0, 28.7, 1.07)
    q_small = model_quality(30.0, 28.7, 1.07)
    assert q_large < 28.7
    assert q_small < q_large
    # The Coulomb term is per full cycle (2 * coulomb_deg / A), the same basis as the
    # viscous term and the qeff curve it overlays. At A=30 that is
    # pi / (pi/28.7 + 2*1.07/30) ~= 17.4, not the ~21.6 a half-swing term would give.
    assert q_small == pytest.approx(17.4, abs=0.3)


@pytest.mark.unit
def test_empty_capture_returns_nothing(tmp_path) -> None:
    """A header-only capture yields no measured amplitudes rather than raising."""
    path = tmp_path / "empty.tsv"
    path.write_text("seq\tus\tcounts\tphi\tstate\n")
    assert sweep(path, COUNTS_PER_DEGREE) == ()


def _write_with_overtop(path, cpr: int, rest: int = 0) -> None:
    """Two swings settling at rest, then one segment that nets one turn away by `cpr`.

    The over-the-top segment ramps past a full turn's worth of counts and settles a
    revolution from the others. That displacement is what `counts_per_rev` reads. It is
    written in raw counts so that the scale is never assumed.
    """
    lines = ["seq\tus\tcounts\tphi\tstate"]
    seq = 0
    us = 0

    def pump() -> None:
        nonlocal seq, us
        for _ in range(6):
            lines.append(f"{seq}\t{us}\t{rest}\t100\tP")
            seq += 1
            us += 2000

    def held(counts) -> None:
        nonlocal seq, us
        for c in counts:
            lines.append(f"{seq}\t{us}\t{int(round(c))}\t0\tH")
            seq += 1
            us += 2000

    # Two ordinary decays, settling back at rest as Coulomb friction stops them dead.
    for amp in (30.0, 20.0):
        pump()
        decay = _decay_counts(FREQUENCY_HZ, 6.0, amp, 3.0, rest)
        settled = [rest + (1 if i % 2 else -1) for i in range(600)]
        held(decay + settled)
    # One segment carried over the top: out to ~1.4 turns, settling one turn away.
    pump()
    peak = rest - int(cpr * 1.4)
    settle = rest - cpr
    ramp = [rest + (peak - rest) * i / 200 for i in range(200)]
    fall = [peak + (settle - peak) * i / 300 for i in range(300)]
    tail = [settle + (1 if i % 2 else -1) for i in range(600)]
    held(ramp + fall + tail)
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.unit
def test_counts_per_rev_from_the_over_the_top_segment(tmp_path) -> None:
    """The settled one-turn displacement reads counts per revolution."""
    path = tmp_path / "pump.tsv"
    _write_with_overtop(path, cpr=2400)
    assert counts_per_rev(path) == pytest.approx(2400, abs=2)


@pytest.mark.unit
def test_counts_per_rev_none_without_an_over_the_top_segment(tmp_path) -> None:
    """No segment over the top means no scale to read, and the result is None."""
    path = tmp_path / "pump.tsv"
    _write_capture(path, [40.0, 30.0, 20.0])
    assert counts_per_rev(path) is None

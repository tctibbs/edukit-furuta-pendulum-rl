"""Large-amplitude ring-downs from the identification firmware's mode d.

Mode d pumps the pendulum to a series of target amplitudes, cuts drive, and logs each
free decay (`docs/runbooks/edukit-firmware.md`). This module reports the effective
quality factor against amplitude, which the small-angle fit in `freeswing.py` cannot
reach. Two things that module does not do:

- split one capture into its pump-then-decay segments, on the drive state column, so
  each target amplitude is fitted on its own decay
- predict the Q_eff the planar model gives, on the same per-cycle basis the hardware is
  read on

Standard library only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from furuta.freeswing import (
    MICROSECONDS_PER_SECOND,
    Trace,
    find_peaks,
    fit_mixed_damping,
    frequency_from_crossings,
)

# Samples of settled tail used as a segment's rest datum, about one second at the
# 500 Hz logging tick. One second averages out the encoder's one-count dither and fits
# inside the settled portion of the shortest decay.
_SETTLE_SAMPLES = 500


@dataclass(frozen=True)
class RingdownSegment:
    """One pump-then-decay cycle from a mode d capture, decay portion only."""

    target_amplitude_deg: float
    trace: Trace


@dataclass(frozen=True)
class AmplitudeQ:
    """Effective quality factor measured over one decay, at its mean amplitude."""

    amplitude_deg: float
    quality: float
    # Coulomb loss per half swing, in degrees, from the same fit. The dry-friction term
    # the simulator does not yet carry.
    coulomb_deg: float


def read_state_trace(
    path: str | Path, counts_per_degree: float
) -> tuple[Trace, tuple[str, ...]]:
    """Read a mode d capture, keeping the five-column lines and the drive state.

    Mode d lines are `seq  us  counts  phi  state`, where state is P during the pump and
    H during the held decay. Returns a `Trace` over the whole capture and the per-sample
    state letters. `split_segments` uses them to keep only the decays. A reset or a
    dropped byte leaves a partial line. Unparsable lines are skipped, as in
    `freeswing.read_trace`.
    """
    times: list[float] = []
    counts: list[float] = []
    states: list[str] = []
    for line in Path(path).read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            continue
        try:
            microseconds = int(fields[1])
            count = int(fields[2])
        except ValueError:
            continue
        state = fields[4].strip()
        if state not in ("P", "H"):
            continue
        times.append(microseconds / MICROSECONDS_PER_SECOND)
        counts.append(count)
        states.append(state)

    if not times:
        return Trace((), (), counts_per_degree), ()

    # Rest angle from the held samples only. The decays are where the pendulum settles;
    # the pump samples carry the drive's bias.
    held = [c for c, s in zip(counts, states, strict=False) if s == "H"]
    rest = median(held) if held else median(counts)
    trace = Trace(
        tuple(times),
        tuple((c - rest) / counts_per_degree for c in counts),
        counts_per_degree,
    )
    return trace, tuple(states)


def split_segments(
    trace: Trace, states: tuple[str, ...]
) -> tuple[RingdownSegment, ...]:
    """Cut a mode d capture into its held decays, one per target amplitude.

    A segment is a run of H samples bounded by P samples on either side. The decay's
    largest turning point is its target amplitude. The timestamps within each segment
    are re-zeroed so a segment can be fitted as if it were a standalone release.
    """
    segments: list[RingdownSegment] = []
    start: int | None = None
    for index, state in enumerate(states):
        if state == "H" and start is None:
            start = index
        elif state == "P" and start is not None:
            segments.append(_segment_from_slice(trace, start, index))
            start = None
    if start is not None:
        segments.append(_segment_from_slice(trace, start, len(states)))
    return tuple(s for s in segments if s is not None)


def _segment_from_slice(trace: Trace, start: int, end: int) -> RingdownSegment | None:
    """Build a segment from a slice, re-zeroed in time and about its own rest.

    The datum is the segment's own median. A symmetric decaying swing spends equal time
    either side of rest, so its median is the rest whether or not the decay ran to a
    stop. The capture-wide median is not: a segment pumped over the top contributes one-
    sided rotation samples that drag the global datum off every other segment. Returns
    None if the slice is too short.
    """
    if end - start < 4:
        return None
    time0 = trace.time_s[start]
    angles = list(trace.angle_deg[start:end])
    rest = median(angles)
    sub = Trace(
        tuple(t - time0 for t in trace.time_s[start:end]),
        tuple(a - rest for a in angles),
        trace.counts_per_degree,
    )
    peaks = find_peaks(sub, minimum_deg=0.0)
    if not peaks:
        return None
    target = max(abs(p.amplitude_deg) for p in peaks)
    return RingdownSegment(target_amplitude_deg=target, trace=sub)


def measure(segment: RingdownSegment) -> AmplitudeQ | None:
    """Effective Q and Coulomb loss for one decay, at the mean of its peak amplitudes.

    Returns None when the decay has too few peaks, or the fit comes back unphysical. A
    release from near vertical lingers at the top for several near-equal turning points,
    and that flat lead-in pulls the fit to a Coulomb term a degree or more negative. The
    cut is at half a degree: below this unit's ~1 degree bite, above the noise a
    frictionless plant would show.
    """
    peaks = find_peaks(segment.trace, minimum_deg=0.0)
    if len(peaks) < 4:
        return None
    frequency, _ = frequency_from_crossings(segment.trace)
    if frequency <= 0.0:
        return None
    damping = fit_mixed_damping(peaks, frequency)
    if damping is None:
        return None
    if damping.viscous_quality <= 0.0 or damping.coulomb_deg < -0.5:
        return None
    amplitudes = [abs(p.amplitude_deg) for p in peaks]
    return AmplitudeQ(
        amplitude_deg=sum(amplitudes) / len(amplitudes),
        quality=damping.viscous_quality,
        coulomb_deg=damping.coulomb_deg,
    )


def qeff_vs_amplitude(segment: RingdownSegment) -> tuple[tuple[float, float], ...]:
    """Effective Q at each amplitude, read straight off one decay's peaks.

    This assumes nothing about linearity, so unlike `measure` it reaches the swing-up
    regime. For a viscous decay the amplitude falls by a fixed fraction each full cycle,
    to first order the log decrement `pi / Q`. A drop of `loss` across one full cycle
    gives `Q_eff = pi / loss` at that amplitude.

    Peaks are paired same-side rather than consecutive. Consecutive peaks sit either
    side of equilibrium, so any error in the rest datum makes the two sides unequal. A
    peak and the next on its own side share that error, and their ratio divides it out.

    Pairs come back raw and noisy. Bin them to read the trend.
    """
    peaks = find_peaks(segment.trace, minimum_deg=0.0)
    out: list[tuple[float, float]] = []
    for first, second in zip(peaks, peaks[2:], strict=False):
        high = abs(first.amplitude_deg)
        low = abs(second.amplitude_deg)
        if high > low > 0 and high > 1.0:
            loss = (high - low) / high
            if loss > 1e-4:
                out.append((high, math.pi / loss))
    return tuple(out)


def model_quality(
    amplitude_deg: float, viscous_quality: float, coulomb_deg_per_half: float
) -> float:
    """Effective Q the planar model gives at an amplitude, for the hardware overlay.

    Read per full cycle, matching the pairing in `qeff_vs_amplitude`. The viscous term
    removes `pi / Q_visc` of the amplitude per cycle, Coulomb removes `2 * coulomb_deg`:

        Q_eff(A) = pi / (pi / Q_visc + 2 * coulomb_deg / A)

    That tends to the viscous Q at large amplitude and falls toward Coulomb near
    hanging. `freeswing.fit_mixed_damping` fits the same decomposition from the other
    direction.
    """
    if amplitude_deg <= 0.0 or viscous_quality <= 0.0:
        return float("nan")
    viscous_loss = math.pi / viscous_quality
    coulomb_loss = 2.0 * coulomb_deg_per_half / amplitude_deg
    return math.pi / (viscous_loss + coulomb_loss)


def sweep(
    path: str | Path, counts_per_degree: float = 6.666667
) -> tuple[AmplitudeQ, ...]:
    """Read a mode d capture and return the measured Q at each target amplitude."""
    trace, states = read_state_trace(path, counts_per_degree)
    measured = [measure(segment) for segment in split_segments(trace, states)]
    return tuple(m for m in measured if m is not None)


def counts_per_rev(path: str | Path) -> float | None:
    """Encoder counts per revolution from where the over-the-top segment settled.

    The pump's highest target carries the pendulum past vertical, and it settles hanging
    again but a whole revolution away in the unwrapped count. That offset from the
    segments that only swung is one revolution in raw counts, so the calculation takes
    no scale.

    Returns None unless the rotating segment made exactly one net turn, checked by its
    farthest excursion lying between one and two revolutions of the settled
    displacement.
    """
    settled, excursions = _segment_rest_and_reach(path)
    if len(settled) < 2:
        return None
    baseline = median(settled)
    displacements = [abs(s - baseline) for s in settled]
    far = max(range(len(settled)), key=lambda i: displacements[i])
    displacement = displacements[far]
    if displacement < 1500.0:  # nothing cleared the top; a swing stays under ~1250
        return None
    reach = abs(excursions[far] - baseline)
    if displacement <= reach < 2.0 * displacement:  # one net turn
        return displacement
    return None


def _segment_rest_and_reach(
    path: str | Path,
) -> tuple[list[float], list[float]]:
    """Settled-tail count and farthest count for each held decay, in raw counts.

    Splits the capture on the P/H drive-state column the way `read_state_trace` does,
    but keeps raw counts. Returns one settled count and one extreme count per held run.
    """
    rests: list[float] = []
    reaches: list[float] = []
    current: list[int] = []

    def close(run: list[int]) -> None:
        if len(run) < _SETTLE_SAMPLES:
            return
        rests.append(median(run[-_SETTLE_SAMPLES:]))
        reaches.append(max(run, key=abs))

    for line in Path(path).read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            continue
        try:
            count = int(fields[2])
        except ValueError:
            continue
        state = fields[4].strip()
        if state == "H":
            current.append(count)
        elif state == "P":
            close(current)
            current = []
    close(current)
    return rests, reaches

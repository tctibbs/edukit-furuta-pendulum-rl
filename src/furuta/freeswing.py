"""Fit a free-swing ring-down to get the suspended-mode frequency and Q.

The trace comes from `scripts/capture_trace.py`.

The frequency comes from a fit rather than a transform. At Q around 20 the resonance
linewidth is f/Q, about 0.06 Hz, so resolving the 2 percent gate by transform would need
a 42 second record. The trace has decayed into quantization noise well before that.
Counting zero crossings over the cycles that do exist gives the frequency directly.

The decay answers a second question. `parameters.py` models pivot loss as viscous, `c =
I*omega/Q`. The two mechanisms leave different fingerprints in the peaks: viscous drag
decays the envelope exponentially, Coulomb friction decays it linearly. Fitting both
says which dominates.

Standard library only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median

# The firmware emits microseconds and raw encoder counts. The conversions live here. A
# trace file holds the values the board sent.
MICROSECONDS_PER_SECOND = 1_000_000.0

# The amplitude band the quoted frequency is measured in.
#
# Upper: a pendulum is only harmonic for small swings. The leading correction is
# T = T0 * (1 + theta^2/16), 6 percent at 56 degrees. Averaging a whole
# ring-down from a large release biases the frequency low by more than the 2 percent
# gate. At 15 degrees the term is 0.43 percent and can be ignored.
#
# Lower: the encoder resolves 0.15 degrees. Below about 3 degrees one count is a
# large share of the swing and the turning points stop being timeable.
LINEAR_BAND_LOW_DEG = 3.0
LINEAR_BAND_HIGH_DEG = 15.0


@dataclass(frozen=True)
class Trace:
    """A captured trace, in seconds and degrees from the pendulum's rest position."""

    time_s: tuple[float, ...]
    angle_deg: tuple[float, ...]
    counts_per_degree: float = 6.666667

    @property
    def resolution_deg(self) -> float:
        """One encoder count, in degrees. The floor on any amplitude claim."""
        return 1.0 / self.counts_per_degree

    def __len__(self) -> int:
        """Number of samples."""
        return len(self.time_s)

    @property
    def duration_s(self) -> float:
        """Elapsed time from first to last sample."""
        return self.time_s[-1] - self.time_s[0] if self.time_s else 0.0

    @property
    def sample_rate_hz(self) -> float:
        """Mean rate implied by the board's own timestamps.

        The firmware's nominal logging rate is 500 Hz.
        """
        return (len(self) - 1) / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def sample_interval_jitter_s(self) -> float:
        """Standard deviation of the interval between consecutive samples."""
        if len(self) < 3:
            return 0.0
        gaps = [b - a for a, b in zip(self.time_s, self.time_s[1:], strict=False)]
        mean = sum(gaps) / len(gaps)
        return math.sqrt(sum((g - mean) ** 2 for g in gaps) / len(gaps))


@dataclass(frozen=True)
class Peak:
    """One turning point of the oscillation."""

    time_s: float
    amplitude_deg: float


@dataclass(frozen=True)
class ModelFit:
    """How well one decay law explains the peak amplitudes."""

    name: str
    r_squared: float
    # Exponential: amplitude = initial * exp(-t/tau). Linear: initial - rate * t.
    initial_deg: float
    tau_s: float | None = None
    rate_deg_per_s: float | None = None


@dataclass(frozen=True)
class MixedDamping:
    """Viscous drag and Coulomb friction fitted together. This unit shows both.

    Per half swing the amplitude drops by `viscous_fraction * A + coulomb_deg`. The
    first term is drag rising with speed, the second a constant friction torque. A
    single-mechanism fit returns a quality factor that depends on the amplitudes in the
    fit window.
    """

    viscous_fraction: float
    coulomb_deg: float
    r_squared: float
    # Amplitude at which the two terms contribute equally. Below this, dry friction is
    # the dominant loss. A balance controller operates below it.
    crossover_deg: float
    # Q of the viscous term alone.
    viscous_quality: float


@dataclass(frozen=True)
class FreeSwingResult:
    """Everything one ring-down yields."""

    frequency_hz: float
    quality_factor: float
    tau_s: float
    cycles: int
    peaks: tuple[Peak, ...]
    viscous: ModelFit
    coulomb: ModelFit
    # Frequency averaged over the whole ring-down, including the large swings where the
    # pendulum is not harmonic. Kept because the gap between the two is the size of the
    # nonlinear bias.
    frequency_whole_hz: float = 0.0
    band_cycles: int = 0
    # (amplitude in degrees, frequency implied by that half period) for each pair of
    # turning points. The band bounds were read off these pairs.
    amplitude_frequency: tuple[tuple[float, float], ...] = ()
    mixed: MixedDamping | None = None

    @property
    def quality_factor_is_meaningful(self) -> bool:
        """Whether quoting a single Q describes this pendulum.

        It does not when a constant friction term acts over the range that matters. The
        decay is then not exponential and the fitted Q depends on which amplitudes went
        into it. On this unit it runs from about 16 at large swings to about 6 at small
        ones.

        The test is the crossover angle, below which dry friction is the larger loss. A
        crossover under a couple of degrees means viscous drag governs wherever the
        pendulum spends real time. This unit's is near 20 degrees.
        """
        return self.mixed is not None and self.mixed.crossover_deg < 2.0

    @property
    def damping_verdict(self) -> str:
        """Which decay law fits the envelope better, or neither decisively.

        The margin is 0.02 in r-squared. These are two-parameter fits to a handful of
        peaks. A smaller difference in r-squared is not evidence of a mechanism.
        """
        gap = self.viscous.r_squared - self.coulomb.r_squared
        if gap > 0.02:
            return "viscous"
        if gap < -0.02:
            return "coulomb"
        return "indistinguishable"


def read_trace(path: str | Path, counts_per_degree: float) -> Trace:
    """Read a captured trace, converting to seconds and degrees about the rest angle.

    Lines that are not two integers are skipped. The capture keeps whatever the board
    sent, and a reset or a dropped byte mid-stream leaves a partial line.
    """
    times: list[float] = []
    counts: list[float] = []
    for line in Path(path).read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 2:
            continue
        try:
            microseconds, count = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        times.append(microseconds / MICROSECONDS_PER_SECOND)
        counts.append(count)

    if not times:
        return Trace((), (), counts_per_degree)

    # The encoder is incremental. A count carries no absolute angle. The pendulum spends
    # most of a ring-down near its rest position, and the median finds that position
    # without being pulled by the large early swings.
    rest = median(counts)
    return Trace(
        tuple(times),
        tuple((c - rest) / counts_per_degree for c in counts),
        counts_per_degree,
    )


def find_peaks(trace: Trace, minimum_deg: float = 0.0) -> tuple[Peak, ...]:
    """Return the turning points, as absolute amplitude about rest.

    A turning point is a sample whose neighbours are both on the same side of it. Runs
    of equal samples are treated as one turning point at their first sample.
    Quantization makes flat tops common near the end of a decay.
    """
    peaks: list[Peak] = []
    angles, times = trace.angle_deg, trace.time_s
    index = 1
    while index < len(angles) - 1:
        previous, current = angles[index - 1], angles[index]
        run_end = index
        while run_end + 1 < len(angles) and angles[run_end + 1] == current:
            run_end += 1
        following = angles[run_end + 1] if run_end + 1 < len(angles) else current
        rising_then_falling = previous < current > following
        falling_then_rising = previous > current < following
        if (rising_then_falling or falling_then_rising) and abs(current) >= minimum_deg:
            peaks.append(Peak(times[index], abs(current)))
        index = run_end + 1
    return tuple(peaks)


def frequency_from_crossings(
    trace: Trace, deadband_counts: float = 2.0
) -> tuple[float, int]:
    """Estimate frequency by timing zero crossings, and report the cycles counted.

    Both details below came from feeding the fit a synthetic trace whose answer was
    known.

    A raw sign test overcounts. The encoder quantizes to about 0.15 degrees, so as the
    pendulum drifts through rest the reported angle dithers across zero and every
    crossing registers. A crossing is confirmed only once the signal reaches
    `deadband_counts` on the far side, beyond the quantization step.

    The crossing is then timed by interpolating between the samples that straddle zero.
    At 500 Hz against 1.2 Hz the sample grid would otherwise quantize each half period
    by about 0.24 percent, against a 2 percent gate.
    """
    deadband = deadband_counts / trace.counts_per_degree
    crossings: list[float] = []
    angles, times = trace.angle_deg, trace.time_s
    state = 0  # which side of zero the signal was last confirmed on
    pending: float | None = None

    for index in range(len(angles) - 1):
        first, second = angles[index], angles[index + 1]
        # Remember where the signal last passed through zero, for use once the crossing
        # is confirmed. Later straddles overwrite earlier ones. Dithering resolves to
        # the final departure.
        if first != second and (first <= 0.0 <= second or first >= 0.0 >= second):
            span = second - first
            pending = times[index] + (-first / span) * (times[index + 1] - times[index])

        if state <= 0 and second > deadband:
            if state != 0 and pending is not None:
                crossings.append(pending)
            state, pending = 1, None
        elif state >= 0 and second < -deadband:
            if state != 0 and pending is not None:
                crossings.append(pending)
            state, pending = -1, None

    if len(crossings) < 3:
        return 0.0, 0
    # Consecutive crossings are half a period apart.
    half_periods = len(crossings) - 1
    elapsed = crossings[-1] - crossings[0]
    frequency = half_periods / (2.0 * elapsed) if elapsed > 0 else 0.0
    return frequency, half_periods // 2


def _least_squares(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Fit y = slope*x + intercept. Returns slope, intercept and r-squared."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    if variance_x == 0:
        return 0.0, mean_y, 0.0
    slope = covariance / variance_x
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for y in ys)
    residual = sum(
        (y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=False)
    )
    r_squared = 1.0 - residual / total if total > 0 else 0.0
    return slope, intercept, r_squared


def fit_viscous(peaks: tuple[Peak, ...]) -> ModelFit:
    """Fit amplitude = initial * exp(-t / tau), by regressing log amplitude on time."""
    usable = [p for p in peaks if p.amplitude_deg > 0.0]
    if len(usable) < 2:
        return ModelFit("viscous", 0.0, 0.0, tau_s=None)
    start = usable[0].time_s
    xs = [p.time_s - start for p in usable]
    ys = [math.log(p.amplitude_deg) for p in usable]
    slope, intercept, r_squared = _least_squares(xs, ys)
    tau = -1.0 / slope if slope < 0 else float("inf")
    return ModelFit("viscous", r_squared, math.exp(intercept), tau_s=tau)


def fit_coulomb(peaks: tuple[Peak, ...]) -> ModelFit:
    """Fit amplitude = initial - rate * t, the signature of constant friction."""
    if len(peaks) < 2:
        return ModelFit("coulomb", 0.0, 0.0, rate_deg_per_s=None)
    start = peaks[0].time_s
    xs = [p.time_s - start for p in peaks]
    ys = [p.amplitude_deg for p in peaks]
    slope, intercept, r_squared = _least_squares(xs, ys)
    return ModelFit("coulomb", r_squared, intercept, rate_deg_per_s=-slope)


def amplitude_frequency_pairs(trace: Trace) -> tuple[tuple[float, float], ...]:
    """Frequency implied by each half period, against the mean amplitude over it.

    A harmonic oscillator would give a flat line. A real pendulum slopes down with
    amplitude. `LINEAR_BAND_LOW_DEG` and `LINEAR_BAND_HIGH_DEG` bound the fit to the
    flat part.
    """
    peaks = find_peaks(trace, minimum_deg=0.0)
    pairs = []
    for first, second in zip(peaks, peaks[1:], strict=False):
        half = second.time_s - first.time_s
        if half <= 0:
            continue
        amplitude = (first.amplitude_deg + second.amplitude_deg) / 2.0
        pairs.append((amplitude, 1.0 / (2.0 * half)))
    return tuple(pairs)


def linear_band(trace: Trace) -> Trace:
    """The stretch of a ring-down where the swing is small enough to be harmonic.

    Runs from the first turning point at or below `LINEAR_BAND_HIGH_DEG` to the first
    one below `LINEAR_BAND_LOW_DEG`. Returns an empty trace when the release never
    entered the band or decayed through it too fast to leave anything.
    """
    peaks = find_peaks(trace, minimum_deg=0.0)
    start = next(
        (p.time_s for p in peaks if p.amplitude_deg <= LINEAR_BAND_HIGH_DEG), None
    )
    if start is None:
        return Trace((), (), trace.counts_per_degree)
    end = next(
        (
            p.time_s
            for p in peaks
            if p.time_s > start and p.amplitude_deg < LINEAR_BAND_LOW_DEG
        ),
        trace.time_s[-1],
    )
    kept = [i for i, t in enumerate(trace.time_s) if start <= t <= end]
    return Trace(
        tuple(trace.time_s[i] for i in kept),
        tuple(trace.angle_deg[i] for i in kept),
        trace.counts_per_degree,
    )


def split_on_reexcitation(
    segments: tuple[Trace, ...], growth: float = 1.5
) -> tuple[Trace, ...]:
    """Split any segment where the swing grows again.

    A free ring-down only ever decays. A peak `growth` times its predecessor is energy
    going back in. On this bench that means the pendulum was picked up for the next
    release before the previous had settled. Two ring-downs in one segment fit as a
    single decay.
    """
    out: list[Trace] = []
    for segment in segments:
        peaks = find_peaks(segment, minimum_deg=LINEAR_BAND_LOW_DEG)
        cuts = [
            second.time_s
            for first, second in zip(peaks, peaks[1:], strict=False)
            if second.amplitude_deg > first.amplitude_deg * growth
        ]
        if not cuts:
            out.append(segment)
            continue
        bounds = [segment.time_s[0], *cuts, segment.time_s[-1] + 1.0]
        for low, high in zip(bounds, bounds[1:], strict=False):
            kept = [i for i, t in enumerate(segment.time_s) if low <= t < high]
            if len(kept) > 1:
                out.append(
                    Trace(
                        tuple(segment.time_s[i] for i in kept),
                        tuple(segment.angle_deg[i] for i in kept),
                        segment.counts_per_degree,
                    )
                )
    return tuple(out)


def fit_mixed_damping(
    peaks: tuple[Peak, ...], frequency_hz: float, maximum_deg: float = 30.0
) -> MixedDamping | None:
    """Fit amplitude lost per half swing as `fraction * A + constant`.

    Regressing the drop against the amplitude it started from separates the two
    mechanisms. The slope is the viscous part, the intercept the Coulomb part. This
    pendulum returns both non-zero.

    `maximum_deg` is there because the model is linear in amplitude. Above roughly 30
    degrees the swing is far enough from harmonic that the loss stops being linear, and
    those points carry the most leverage. Including them returns a negative constant
    term for a large release, and friction cannot be negative.
    """
    xs, ys = [], []
    for first, second in zip(peaks, peaks[1:], strict=False):
        if first.amplitude_deg <= 0 or first.amplitude_deg > maximum_deg:
            continue
        xs.append(first.amplitude_deg)
        ys.append(first.amplitude_deg - second.amplitude_deg)
    if len(xs) < 4:
        return None
    slope, intercept, r_squared = _least_squares(xs, ys)
    if slope <= 0:
        return None
    crossover = intercept / slope if slope else float("inf")
    # Per half swing the viscous term removes `slope` of the amplitude. The envelope
    # time constant is (T/2)/slope. Q = pi * f * tau.
    tau = (1.0 / (2.0 * frequency_hz)) / slope if frequency_hz else 0.0
    return MixedDamping(
        viscous_fraction=slope,
        coulomb_deg=intercept,
        r_squared=r_squared,
        crossover_deg=crossover,
        viscous_quality=math.pi * frequency_hz * tau,
    )


def analyse(trace: Trace, minimum_peak_counts: float = 12.0) -> FreeSwingResult:
    """Fit one ring-down.

    `minimum_peak_counts` drops the tail. The fit regresses the logarithm of peak
    amplitude, and quantization cannot report an amplitude below one encoder count, so
    as the swing dies the peaks are biased upward, the envelope appears to flatten, and
    tau and Q inflate. Twelve counts is about 1.8 degrees, where one count is under a
    tenth of the amplitude, and it still leaves two and a half time constants to fit at
    the manual's nominal Q of 20.
    """
    whole_frequency, cycles = frequency_from_crossings(trace)
    band = linear_band(trace)
    band_frequency, band_cycles = (
        frequency_from_crossings(band) if len(band) else (0.0, 0)
    )
    # Fall back to the whole ring-down when the release never entered the band.
    frequency = band_frequency or whole_frequency

    peaks = find_peaks(trace, minimum_deg=minimum_peak_counts / trace.counts_per_degree)
    viscous = fit_viscous(peaks)
    coulomb = fit_coulomb(peaks)
    tau = viscous.tau_s if viscous.tau_s and math.isfinite(viscous.tau_s) else 0.0
    # The quality factor convention used throughout: Q = pi * f * tau.
    quality = math.pi * frequency * tau
    return FreeSwingResult(
        frequency_hz=frequency,
        quality_factor=quality,
        tau_s=tau,
        cycles=cycles,
        peaks=peaks,
        viscous=viscous,
        coulomb=coulomb,
        frequency_whole_hz=whole_frequency,
        band_cycles=band_cycles,
        amplitude_frequency=amplitude_frequency_pairs(trace),
        mixed=fit_mixed_damping(peaks, frequency),
    )


def segment_releases(
    trace: Trace,
    release_deg: float = 5.0,
    rest_counts: float = 3.0,
    quiet_seconds: float = 1.5,
) -> tuple[Trace, ...]:
    """Split a long capture into one Trace per release.

    A release is recognised by a swing exceeding `release_deg`, and is not over until
    the pendulum rests within `rest_counts`. Ending a segment when the swing falls back
    under the detection threshold would throw away most of the decay, which the Q fit
    needs: from a 25 degree release the swing is under 5 degrees after about 9 seconds
    while usable oscillation continues past 20.

    Handling the pendulum between releases makes large irregular excursions this also
    catches. Check the segment count against the number of releases made.
    """
    if not len(trace):
        return ()
    rest_deg = rest_counts / trace.counts_per_degree
    segments: list[Trace] = []
    start: int | None = None
    last_active: int | None = None

    for index, angle in enumerate(trace.angle_deg):
        magnitude = abs(angle)
        if start is None:
            if magnitude >= release_deg:
                start, last_active = index, index
            continue
        if magnitude >= rest_deg:
            last_active = index
        elif (
            last_active is not None
            and trace.time_s[index] - trace.time_s[last_active] >= quiet_seconds
        ):
            segments.append(
                Trace(
                    trace.time_s[start : index + 1],
                    trace.angle_deg[start : index + 1],
                    trace.counts_per_degree,
                )
            )
            start, last_active = None, None

    if start is not None:
        segments.append(
            Trace(
                trace.time_s[start:],
                trace.angle_deg[start:],
                trace.counts_per_degree,
            )
        )
    return tuple(segments)

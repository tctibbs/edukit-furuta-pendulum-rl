"""Replay a logged swing-up's rotor motion through the planar model.

probe-trace runs the real stock swing-up and a brief balance hold, logging the pendulum
and the rotor angle counted from issued steps. This module drives `planar.PlanarModel`
with the measured rotor acceleration and returns the predicted pendulum angle beside the
measured one. No controller reacts in either run, so a gap points to the physics.

The replay integrates open loop from one initial state. The rotor angle is microstep
quantised and its second derivative is delicate, so a small error in the reconstructed
acceleration accumulates as slow phase drift over a long trajectory. Read it for the
deterministic climb and time to vertical, not as a pointwise match cycle after cycle.

Angles are from upright: 0 balanced, +/- 180 deg hanging, the environment's convention.
numpy supplies the Savitzky-Golay derivative; the rest is stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np

from furuta.planar import PlanarModel

MICROSECONDS_PER_SECOND = 1_000_000.0
COUNTS_PER_DEGREE = 6.666667
MICROSTEPS_PER_DEGREE = 8.888889


@dataclass(frozen=True)
class TraceRun:
    """One swing-up (and balance) run: time and angles from upright, in radians."""

    time_s: tuple[float, ...]
    tilt_rad: tuple[float, ...]  # pendulum, from upright
    rotor_rad: tuple[float, ...]  # rotor angle, counted from issued steps
    state: tuple[str, ...]  # 'D' driving up, 'B' balancing, 'H' free


def _wrap(angle: float) -> float:
    """Wrap to [-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def read_trace(
    path: str | Path,
    counts_per_degree: float = COUNTS_PER_DEGREE,
    microsteps_per_degree: float = MICROSTEPS_PER_DEGREE,
) -> tuple[TraceRun, ...]:
    """Read a probe-trace capture and split it into runs.

    Lines are `seq  us  counts  phi  state`. Counts are pendulum encoder counts from
    hanging; the tilt from upright is that angle minus half a turn. A drop in the
    microsecond column marks the start of the next run.
    """
    runs: list[TraceRun] = []
    t: list[float] = []
    tilt: list[float] = []
    rotor: list[float] = []
    state: list[str] = []
    last_us: int | None = None
    us0: int | None = None

    def flush() -> None:
        if len(t) >= 4:
            runs.append(TraceRun(tuple(t), tuple(tilt), tuple(rotor), tuple(state)))
        t.clear()
        tilt.clear()
        rotor.clear()
        state.clear()

    for line in Path(path).read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 5:
            continue
        try:
            us = int(fields[1])
            counts = int(fields[2])
            phi = int(fields[3])
        except ValueError:
            continue
        letter = fields[4].strip()
        if letter not in ("D", "B", "H"):
            continue
        if last_us is not None and us < last_us:
            flush()
            us0 = None
        last_us = us
        if us0 is None:
            us0 = us
        hanging_rad = math.radians(counts / counts_per_degree)
        t.append((us - us0) / MICROSECONDS_PER_SECOND)
        tilt.append(_wrap(hanging_rad - math.pi))
        rotor.append(math.radians(phi / microsteps_per_degree))
        state.append(letter)
    flush()
    return tuple(runs)


def rotor_acceleration(
    time_s, rotor_rad, window: int = 31, order: int = 3
) -> list[float]:
    """Rotor angular acceleration (rad/s^2) via a Savitzky-Golay second derivative.

    The stock swing-up drives the rotor in discrete kicks, so the raw angle is stair
    stepped and a plain second difference is noise. Fitting a low-order polynomial over
    a sliding window and reading its curvature turns each kick into the smooth bump the
    pendulum feels, and the pendulum's own inertia low-passes what remains. On a
    uniform grid the fit reduces to a fixed FIR kernel, one convolution.
    """
    n = len(rotor_rad)
    if n < window + 2 or window < 5:
        return [0.0] * n
    if window % 2 == 0:
        window += 1
    half = window // 2
    dt = (time_s[-1] - time_s[0]) / (n - 1) if n > 1 else 0.002
    grid = np.arange(-half, half + 1) * dt
    basis = np.vander(grid, order + 1, increasing=True)
    # Second derivative at the window centre is 2 * the fitted t^2 coefficient; the
    # pseudo-inverse's row 2 is the linear filter that produces that coefficient.
    kernel = 2.0 * np.linalg.pinv(basis)[2]
    y = np.asarray(rotor_rad, dtype=float)
    padded = np.concatenate([np.full(half, y[0]), y, np.full(half, y[-1])])
    acc = np.convolve(padded, kernel[::-1], mode="valid")
    return acc.tolist()


def replay(run: TraceRun, model: PlanarModel | None = None) -> list[float]:
    """Model pendulum tilt (rad from upright) driven by the run's measured rotor motion.

    Starts from the measured initial tilt and a rate estimated from the first samples,
    then integrates the planar model on the run's own time grid, feeding the measured
    rotor acceleration at each step.
    """
    model = model or PlanarModel.from_parameters()
    t = run.time_s
    n = len(t)
    accel = rotor_acceleration(t, run.rotor_rad)
    theta = run.tilt_rad[0]
    # A swing-up starts at hanging, where the wrapped tilt sits on the +/-pi branch cut,
    # so a raw difference of two wrapped angles can jump by ~2 pi on a single encoder
    # count. Wrapping the delta takes the rate the short way round.
    span = min(8, n - 1)
    if span >= 2 and (t[span] - t[0]) > 0:
        theta_dot = _wrap(run.tilt_rad[span] - run.tilt_rad[0]) / (t[span] - t[0])
    else:
        theta_dot = 0.0
    out = [theta]
    for i in range(1, n):
        dt = t[i] - t[i - 1]
        if dt <= 0 or dt > 0.1:
            dt = 0.002
        theta, theta_dot = model.step(theta, theta_dot, accel[i - 1], dt)
        out.append(theta)
    return out


GAP_S = 0.030
"""Floor for calling a sample spacing a dropout. See `dropout_indices`."""

GAP_RATIO = 4.0
"""How many times the run's median spacing a gap must be to count as a dropout."""


def dropout_indices(time_s, state=None, gap_s: float = GAP_S, ratio: float = GAP_RATIO):
    """Indices `i` where the log skipped between sample `i` and `i + 1`.

    A capture's phases log at different rates, so the threshold is relative to the local
    spacing rather than fixed. The swing-up logs every 13 ms and skips 198 ms windows,
    which are dropouts. The balance hold logs every 200 ms from end to end, and a fixed
    threshold calls that whole phase one dropout and then invents rotor motion across
    all of it.

    Pass `state` to compare each phase against its own rate. Without it the median
    follows whichever phase has more samples. The seam
    between two phases is never a dropout: the firmware restarted its clock there and
    nothing was skipped.
    """
    times = np.asarray(time_s)
    deltas = np.diff(times)
    if deltas.size == 0:
        return np.empty(0, dtype=int)

    if state is None:
        blocks = [(0, len(times))]
    else:
        blocks = []
        start = 0
        for i in range(1, len(state) + 1):
            if i == len(state) or state[i] != state[start]:
                blocks.append((start, i))
                start = i

    found: list[int] = []
    for lo, hi in blocks:
        inner = deltas[lo : hi - 1]
        if inner.size == 0:
            continue
        threshold = max(gap_s, ratio * float(np.median(inner)))
        found.extend((lo + np.nonzero(inner > threshold)[0]).tolist())
    return np.asarray(sorted(found), dtype=int)


def _bangbang(t_start: float, t_end: float, x0: float, x1: float, grid) -> np.ndarray:
    """Rotor angle across one dropout under a symmetric accelerate-then-brake move.

    The capture records only the endpoints of each window, so this profile and the
    straight line are both guesses.

    This profile is the fastest symmetric rest-to-rest move that uses the whole window.
    It does not bound the impulse the rotor could have delivered: a move that finishes
    early inside the window is faster and differently timed against the swing. The space
    of profiles the capture permits is much larger than these two.
    """
    span = t_end - t_start
    half = span / 2.0
    accel = 4.0 * (x1 - x0) / (span * span)
    tau = np.clip(np.asarray(grid) - t_start, 0.0, span)
    first = tau <= half
    out = np.where(
        first,
        x0 + 0.5 * accel * tau**2,
        x1 - 0.5 * accel * (span - tau) ** 2,
    )
    return out


def resample_to_grid(
    run: TraceRun, dt: float, gap_profile: str = "linear"
) -> tuple[list[float], list[float], list[float], list[str]]:
    """Put one run on a grid of `dt`: time, rotor, measured tilt, and phase letter.

    The capture is logged every 12 to 13 ms, and a simulator steps its controller at
    2 ms, so a replay has to interpolate. The rotor column holds two values, and every
    transition between them falls inside a 198 ms window where nothing was logged. The
    shape of that move is the input the pendulum integrates, and it was never recorded.

    `gap_profile` picks what to assume in those windows. `linear` draws the straight
    line between the endpoints. `bangbang` accelerates for half the window and brakes
    for the other half. Neither is measured. Running both shows how much the replay's
    answer rests on the assumption.

    Tilt is interpolated on the unwrapped angle. Interpolating the wrapped one averages
    across the +/-pi branch cut and puts a spurious sweep through zero in the middle of
    a swing that never left the bottom.
    """
    if gap_profile not in ("linear", "bangbang"):
        raise ValueError(f"gap_profile must be linear or bangbang, got {gap_profile!r}")

    n = int(run.time_s[-1] / dt) + 1
    grid = [i * dt for i in range(n)]
    times = np.asarray(run.time_s)
    rotor = np.interp(grid, times, np.asarray(run.rotor_rad))

    if gap_profile == "bangbang":
        angles = np.asarray(run.rotor_rad)
        grid_array = np.asarray(grid)
        for i in dropout_indices(times, run.state):
            if angles[i + 1] == angles[i]:
                continue
            inside = (grid_array >= times[i]) & (grid_array <= times[i + 1])
            rotor[inside] = _bangbang(
                times[i], times[i + 1], angles[i], angles[i + 1], grid_array[inside]
            )

    unwrapped = np.unwrap(np.asarray(run.tilt_rad))
    tilt = [_wrap(float(a)) for a in np.interp(grid, times, unwrapped)]

    # Phase is a label, so it takes the value of the sample it is at or just after
    # instead of being interpolated.
    where = np.searchsorted(times, np.asarray(grid), side="right") - 1
    state = [run.state[int(min(max(i, 0), len(run.state) - 1))] for i in where]
    return grid, rotor.tolist(), tilt, state


def join_runs(runs: tuple[TraceRun, ...]) -> TraceRun:
    """Concatenate a capture's runs back into one continuous recording.

    `probe-trace` restarts its microsecond counter when it hands over from the swing-up
    to the balance hold, so `read_trace` sees two runs where the machine did one thing.
    They join cleanly: the swing-up ends at the rotor angle the balance hold starts
    from, and within a degree of the same tilt.

    The seam itself is not measured. The counter reset hides however long the handover
    took, and this places the second run one median sample after the first ends, the
    shortest gap consistent with the log. Anything the seam does to a replay is an
    artifact of that choice.
    """
    if not runs:
        raise ValueError("no runs to join")
    if len(runs) == 1:
        return runs[0]

    time_s: list[float] = []
    tilt: list[float] = []
    rotor: list[float] = []
    state: list[str] = []
    offset = 0.0
    for run in runs:
        time_s.extend(t + offset for t in run.time_s)
        tilt.extend(run.tilt_rad)
        rotor.extend(run.rotor_rad)
        state.extend(run.state)
        deltas = [b - a for a, b in zip(run.time_s, run.time_s[1:], strict=False)]
        step = median(deltas) if deltas else 0.002
        offset = time_s[-1] + step
    return TraceRun(tuple(time_s), tuple(tilt), tuple(rotor), tuple(state))

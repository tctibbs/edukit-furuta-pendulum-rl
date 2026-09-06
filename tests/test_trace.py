"""Tests for the single-angle pendulum model and the trace replay.

With no hardware here, a known rotor motion is pushed through the model to make a
synthetic capture, and the reader and the replay are asked to recover it.
"""

from __future__ import annotations

import math

import pytest

import furuta.trace as resample_module
from furuta.planar import PlanarModel
from furuta.trace import (
    TraceRun,
    read_trace,
    replay,
    resample_to_grid,
    rotor_acceleration,
)


@pytest.mark.unit
def test_small_angle_period_matches_omega_g() -> None:
    """A tiny release oscillates at the pendulum's natural period, 2 pi / omega_g."""
    m = PlanarModel.from_parameters()
    # 20 deg release: small enough that the period is still the natural one, large
    # enough that dry friction (~1 deg per half swing) leaves several swings.
    theta = math.pi + math.radians(20.0)
    theta_dot = 0.0
    dt = 0.001
    crossings = []
    prev = theta - math.pi
    for i in range(4000):
        theta, theta_dot = m.step(theta, theta_dot, 0.0, dt)
        cur = theta - math.pi
        if prev < 0.0 <= cur:  # upward zero crossing of the offset from hanging
            crossings.append(i * dt)
        prev = cur
    assert len(crossings) >= 2
    period = crossings[1] - crossings[0]
    expected = 2 * math.pi / m.omega_g
    assert period == pytest.approx(expected, rel=0.06)


@pytest.mark.unit
def test_coulomb_friction_brings_it_to_rest() -> None:
    """Dry friction brings a released pendulum to rest in finite time."""
    m = PlanarModel.from_parameters()
    theta = math.pi + math.radians(20.0)
    theta_dot = 0.0
    dt = 0.001
    for _ in range(20000):  # 20 s
        theta, theta_dot = m.step(theta, theta_dot, 0.0, dt)
    assert abs(theta_dot) < 0.05
    assert abs(theta - math.pi) < math.radians(3.0)  # theta = pi is hanging


@pytest.mark.unit
def test_rotor_acceleration_recovers_a_constant() -> None:
    """A constant-acceleration ramp phi = 0.5 a t^2 reads back its acceleration a."""
    a = 4.0  # rad/s^2
    dt = 0.002
    n = 400
    t = [i * dt for i in range(n)]
    phi = [0.5 * a * (i * dt) ** 2 for i in range(n)]
    acc = rotor_acceleration(t, phi, window=31)
    mid = acc[len(acc) // 2]
    assert mid == pytest.approx(a, rel=0.02)


@pytest.mark.unit
def test_read_trace_splits_runs_on_timestamp_reset(tmp_path) -> None:
    """A capture whose microsecond column resets reads back as two runs."""
    lines = ["seq\tus\tcounts\tphi\tstate"]
    for _run in range(2):
        for k in range(50):
            lines.append(f"{k}\t{k * 2000}\t{1200 + k}\t{k}\tD")
    path = tmp_path / "trace.tsv"
    path.write_text("\n".join(lines) + "\n")
    runs = read_trace(path)
    assert len(runs) == 2
    assert all(len(r.time_s) == 50 for r in runs)


@pytest.mark.unit
def test_replay_tracks_a_driven_swing(tmp_path) -> None:
    """Replay recovers a driven trajectory to within the drift `trace.py` documents.

    A smooth rotor motion is pushed through the model to make the "hardware" pendulum,
    written out as a capture the reader and replay must reproduce. The loose tolerance
    admits the slow phase drift of an open-loop replay. Mean error over the run, after
    the first 120 ms of settling, stays under 5 degrees.
    """
    m = PlanarModel.from_parameters()
    dt = 0.002
    n = 2500
    cpd, mpd = 6.666667, 8.888889
    theta = math.pi - 0.25
    theta_dot = 0.0
    lines = ["seq\tus\tcounts\tphi\tstate"]
    truth = []
    for i in range(n):
        t = i * dt
        phi = 0.6 * math.sin(2 * math.pi * 0.6 * t)
        phi_acc = -0.6 * (2 * math.pi * 0.6) ** 2 * math.sin(2 * math.pi * 0.6 * t)
        theta, theta_dot = m.step(theta, theta_dot, phi_acc, dt)
        truth.append(theta)
        counts = round(math.degrees(theta + math.pi) * cpd)
        phi_ms = round(math.degrees(phi) * mpd)
        lines.append(f"{i}\t{i * 2000}\t{counts}\t{phi_ms}\tD")
    path = tmp_path / "trace.tsv"
    path.write_text("\n".join(lines) + "\n")

    run = read_trace(path)[0]
    model_theta = replay(run, m)
    errors = [abs(model_theta[i] - truth[i]) for i in range(60, n)]
    mean_err = sum(errors) / len(errors)
    assert math.degrees(mean_err) < 5.0


@pytest.mark.unit
def test_resample_lands_on_the_requested_grid() -> None:
    """Uniform spacing at the control period, covering the run."""
    run = TraceRun(
        time_s=(0.0, 0.013, 0.026, 0.039),
        tilt_rad=(3.0, 3.01, 3.02, 3.03),
        rotor_rad=(0.0, 0.1, 0.2, 0.3),
        state=("D", "D", "D", "D"),
    )
    grid, rotor, tilt, _ = resample_to_grid(run, 0.002)
    assert len(grid) == len(rotor) == len(tilt)
    assert grid[1] - grid[0] == pytest.approx(0.002)
    assert grid[-1] <= run.time_s[-1] + 1e-9
    # Linear in the rotor, so the midpoint of the first span is the mean of its ends.
    assert rotor[math.floor(0.0065 / 0.002)] == pytest.approx(0.05, abs=0.02)


@pytest.mark.unit
def test_resample_does_not_cross_the_branch_cut() -> None:
    """A swing through hanging must not be interpolated the long way round.

    Wrapped tilt jumps from +pi to -pi on a single encoder count at the bottom. Taken
    literally, a linear interpolation between those two samples sweeps the pendulum past
    upright and back inside 13 ms.
    """
    run = TraceRun(
        time_s=(0.0, 0.013, 0.026),
        tilt_rad=(3.13, -3.13, -3.10),
        rotor_rad=(0.0, 0.0, 0.0),
        state=("D", "D", "D"),
    )
    _, _, tilt, _ = resample_to_grid(run, 0.002)
    assert all(abs(a) > 3.0 for a in tilt)


@pytest.mark.unit
def test_bangbang_gap_matches_the_endpoints() -> None:
    """The alternative profile still passes through what was logged.

    Only the shape inside the dropout differs. The samples either side are measurements
    and neither profile is allowed to move them.
    """
    run = TraceRun(
        time_s=(0.0, 0.013, 0.211, 0.224),
        tilt_rad=(3.10, 3.12, -3.10, -3.05),
        rotor_rad=(0.30, 0.30, 0.69, 0.69),
        state=("D", "D", "D", "D"),
    )
    dt = 0.002
    _, linear, _, _ = resample_to_grid(run, dt, gap_profile="linear")
    grid, bang, _, _ = resample_to_grid(run, dt, gap_profile="bangbang")
    assert linear[0] == pytest.approx(0.30, abs=1e-6)
    assert bang[0] == pytest.approx(0.30, abs=1e-6)
    end = min(range(len(grid)), key=lambda i: abs(grid[i] - 0.211))
    assert bang[end] == pytest.approx(0.69, abs=2e-3)
    mid = min(range(len(grid)), key=lambda i: abs(grid[i] - 0.112))
    assert abs(bang[mid] - linear[mid]) < 1e-6  # symmetric profiles cross at halfway
    # Away from the crossing the profiles must separate, or this proves nothing.
    quarter = min(range(len(grid)), key=lambda i: abs(grid[i] - 0.062))
    assert bang[quarter] < linear[quarter] - 0.01


@pytest.mark.unit
def test_bangbang_respects_the_travel_direction() -> None:
    """A move the other way accelerates the other way."""
    run = TraceRun(
        time_s=(0.0, 0.013, 0.211, 0.224),
        tilt_rad=(3.10, 3.12, -3.10, -3.05),
        rotor_rad=(0.69, 0.69, 0.30, 0.30),
        state=("D", "D", "D", "D"),
    )
    grid, bang, _, _ = resample_to_grid(run, 0.002, gap_profile="bangbang")
    inside = [b for g, b in zip(grid, bang, strict=True) if 0.013 < g < 0.211]
    assert all(b <= 0.69 + 1e-9 for b in inside)
    assert all(b >= 0.30 - 1e-9 for b in inside)


@pytest.mark.unit
def test_unknown_gap_profile_is_rejected() -> None:
    """A typo must not silently fall back to one of the two."""
    run = TraceRun(
        time_s=(0.0, 0.013),
        tilt_rad=(3.10, 3.12),
        rotor_rad=(0.30, 0.30),
        state=("D", "D"),
    )
    with pytest.raises(ValueError, match="gap_profile"):
        resample_to_grid(run, 0.002, gap_profile="smooth")


@pytest.mark.unit
def test_dropouts_are_measured_against_each_phase() -> None:
    """200 ms is a dropout inside a 13 ms log, and the log rate inside a 5 Hz one.

    Judging both phases against one median calls the slower phase one long dropout, and
    a replay then invents rotor motion across the whole of it.
    """
    fast = [0.013 * i for i in range(20)]
    fast_states = ["D"] * 20
    # One real skip in the fast phase.
    fast = fast[:10] + [t + 0.19 for t in fast[10:]]
    slow_start = fast[-1] + 0.2
    slow = [slow_start + 0.2 * i for i in range(10)]
    times = tuple(fast + slow)
    states = tuple(fast_states + ["B"] * 10)

    per_phase = resample_module.dropout_indices(times, states)
    pooled = resample_module.dropout_indices(times)
    assert len(per_phase) == 1, "only the fast phase's skip is a dropout"
    assert len(pooled) > len(per_phase), "pooling misreads the slow phase"


@pytest.mark.unit
def test_join_runs_is_continuous_and_ordered() -> None:
    """Joining restores one recording without moving any measured sample."""
    a = TraceRun((0.0, 0.01, 0.02), (3.0, 2.9, 2.8), (0.1, 0.1, 0.2), ("D", "D", "D"))
    b = TraceRun((0.0, 0.2), (-0.01, 0.01), (0.2, 0.3), ("B", "B"))
    joined = resample_module.join_runs((a, b))
    assert joined.time_s == tuple(sorted(joined.time_s))
    assert joined.time_s[:3] == a.time_s
    assert joined.tilt_rad[3:] == b.tilt_rad
    assert joined.state[3:] == ("B", "B")
    # The seam sits after the first run, by one of its own sample intervals.
    assert joined.time_s[3] == pytest.approx(0.03, abs=1e-9)


@pytest.mark.unit
def test_join_runs_rejects_nothing_to_join() -> None:
    """An empty capture raises rather than returning an empty run."""
    with pytest.raises(ValueError, match="no runs"):
        resample_module.join_runs(())


@pytest.mark.unit
def test_resample_labels_each_grid_point_with_its_phase() -> None:
    """Each grid point takes the phase letter of the sample it came from."""
    run = TraceRun(
        time_s=(0.0, 0.01, 0.02, 0.03),
        tilt_rad=(3.0, 1.0, 0.02, 0.01),
        rotor_rad=(0.0, 0.1, 0.2, 0.2),
        state=("D", "D", "B", "B"),
    )
    grid, _, _, state = resample_to_grid(run, 0.002)
    assert set(state) == {"D", "B"}
    assert state[0] == "D"
    assert state[-1] == "B"
    # The handover happens once.
    assert sum(1 for a, b in zip(state, state[1:], strict=False) if a != b) == 1


def test_arm_rate_term_is_off_by_default_and_flings_the_pendulum_when_on() -> None:
    """The manual's planar model stays exact for callers that pass no arm rate.

    With the term on, a hanging pendulum on an arm turning faster than
    `omega_g / sqrt(kappa)` settles at the conical-pendulum angle
    `acos(omega_g^2 / (kappa * phi_dot^2))` from hanging.
    """
    m = PlanarModel.from_parameters()
    dt = 0.002
    assert 0.9 < m.centrifugal < 1.0
    a = m.step(math.pi - 0.05, 0.0, 0.0, dt)
    b = m.step(math.pi - 0.05, 0.0, 0.0, dt, rotor_rate=0.0)
    assert a == b
    lift_speed = math.sqrt(m.omega_g_squared / m.centrifugal)
    assert lift_speed == pytest.approx(7.45, abs=0.02)
    phi_dot = 9.0
    theta, theta_dot = math.pi - 0.3, 0.0
    for _ in range(3000):
        theta, theta_dot = m.step(theta, theta_dot, 0.0, dt, rotor_rate=phi_dot)
    expected = math.acos(m.omega_g_squared / (m.centrifugal * phi_dot**2))
    assert math.pi - abs(theta) == pytest.approx(expected, abs=math.radians(2.0))

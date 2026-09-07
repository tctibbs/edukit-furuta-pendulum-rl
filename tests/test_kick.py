"""Tests for the firmware kick law and the L6474 move profile.

The bench cannot be run here, so the checks lean on two records of the real machine:
the four move durations the driver arithmetic gives for the amplitudes the firmware
uses (185.2 ms measured for the 200-microstep kick), and the golden trace's kick times
and half-swing peaks. A synthetic count sequence built from those peaks exercises the
detector sample by sample, and the planar model closes the loop from rest at hanging.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
import torch

from furuta.kick import (
    BACKWARD,
    FORWARD,
    KickLaw,
    profile_displacement,
    profile_duration,
    profile_velocity,
)
from furuta.parameters import FurutaParameters
from furuta.planar import PlanarModel

DT = 0.002

# In-loop kick times on the golden trace's clock, which starts when the initial move
# completes (docs/experiments/03-hardware-bringup/trace.tsv; the last sample before
# each change of the dead-reckoned rotor column).
GOLDEN_KICKS_S = (
    0.004,
    0.238,
    0.645,
    1.050,
    1.495,
    1.927,
    2.385,
    2.856,
    3.340,
    3.850,
    4.373,
    4.909,
    5.484,
    6.098,
    6.777,
    7.573,
)

# Peak |count| of each half swing, the first being the initial move's deflection as the
# first poll saw it, then one per kick. 1191 is the final approach that handed over.
GOLDEN_PEAKS = (
    57,
    189,
    246,
    307,
    356,
    421,
    471,
    534,
    582,
    647,
    697,
    771,
    835,
    927,
    1020,
)
GOLDEN_FINAL_APPROACH = 1191

# Emulated from the driver arithmetic with MIN_SPEED 800 and 6000 microsteps/s^2
# (config/edukit.yaml, actuator block). The 200 case is measured at 185.2 ms.
EMULATED_DURATIONS_MS = {200: 185.1, 160: 154.7, 150: 146.8, 130: 130.5}


@pytest.fixture
def params() -> FurutaParameters:
    """Parameters from the project parameter file."""
    return FurutaParameters.from_yaml()


# The profile.


@pytest.mark.unit
@pytest.mark.parametrize("steps", sorted(EMULATED_DURATIONS_MS))
def test_profile_duration_matches_the_driver_arithmetic(
    params: FurutaParameters, steps: int
) -> None:
    """Each firmware amplitude lasts what the driver's arithmetic says, to 0.5 ms."""
    duration_ms = 1000.0 * profile_duration(steps, params)
    assert duration_ms == pytest.approx(EMULATED_DURATIONS_MS[steps], abs=0.5)


@pytest.mark.unit
@pytest.mark.parametrize("steps", [130, 150, 160, 200, 600, 900])
def test_profile_displacement_ends_at_n_microsteps_and_is_monotone(
    params: FurutaParameters, steps: int
) -> None:
    """The move covers exactly `steps` microsteps and never runs backwards.

    600 and 900 exercise the trapezoidal branch, where the ramp reaches MAX_SPEED and
    the driver cruises before braking.
    """
    total = profile_duration(steps, params)
    t = torch.linspace(-0.01, total + 0.01, 4001, dtype=torch.float64)
    d = profile_displacement(t, steps, params)
    expected = steps * params.rad_per_microstep
    assert d[0].item() == 0.0
    assert d[-1].item() == pytest.approx(expected, rel=1e-9)
    at_end = profile_displacement(
        torch.tensor(total, dtype=torch.float64), steps, params
    )
    assert at_end.item() == pytest.approx(expected, rel=1e-9)
    assert bool((d[1:] >= d[:-1]).all())


@pytest.mark.unit
def test_profile_speed_starts_at_min_speed_and_stays_under_max(
    params: FurutaParameters,
) -> None:
    """MIN_SPEED at the first pulse, zero after the last, a peak near the config's.

    The config records the 200-microstep kick peaking at 1348 microsteps/s, which is
    2.647 rad/s; the continuous profile peaks 0.6 percent above the pulse arithmetic.
    """
    total = profile_duration(200, params)
    t = torch.linspace(0.0, total, 2001, dtype=torch.float64)
    v = profile_velocity(t, 200, params)
    assert v[0].item() == pytest.approx(params.profile_min_speed_rad_s)
    assert v.max().item() == pytest.approx(2.647, rel=0.01)
    assert v.max().item() <= params.profile_max_speed_rad_s
    after = profile_velocity(torch.tensor([total, total + 1.0]), 200, params)
    assert torch.all(after == 0.0)
    before = profile_velocity(torch.tensor([-1e-3]), 200, params)
    assert before.item() == 0.0


@pytest.mark.unit
def test_profile_cruises_at_max_speed_above_560_microsteps(
    params: FurutaParameters,
) -> None:
    """Below 560 microsteps the move is triangular; above, it holds MAX_SPEED."""
    short = torch.linspace(0.0, profile_duration(550, params), 4001)
    assert profile_velocity(short, 550, params).max().item() < (
        params.profile_max_speed_rad_s
    )
    long_move = torch.linspace(0.0, profile_duration(900, params), 4001)
    v = profile_velocity(long_move, 900, params)
    cruising = (v >= params.profile_max_speed_rad_s - 1e-6).float().mean().item()
    assert cruising > 0.1


@pytest.mark.unit
def test_profile_velocity_integrates_to_the_displacement(
    params: FurutaParameters,
) -> None:
    """The two functions describe the same move."""
    total = profile_duration(200, params)
    n = 20001
    t = torch.linspace(0.0, total, n, dtype=torch.float64)
    v = profile_velocity(t, 200, params)
    h = total / (n - 1)
    integral = (0.5 * (v[1:] + v[:-1]) * h).sum().item()
    assert integral == pytest.approx(200 * params.rad_per_microstep, rel=1e-3)


# The detector on a synthetic swing.


def _synthetic_counts(dt: float = DT) -> tuple[list[int], list[int], list[int]]:
    """A swing with the golden trace's crossings and peaks, on the golden clock.

    Returns the counts per sample, the sample index of each crossing after the first
    poll, and the sign of the half swing each crossing opens. Each half swing is a half
    sine with the listed peak and starts on an exact zero, so the 0 -> negative rule is
    exercised on every other crossing. The first segment is the initial deflection
    coming back to zero.
    """
    crossings = [round(t / dt) for t in GOLDEN_KICKS_S[1:]]
    counts: list[int] = []
    first = crossings[0]
    for j in range(first):
        counts.append(round(-GOLDEN_PEAKS[0] * math.cos(0.5 * math.pi * j / first)))
    signs: list[int] = []
    for k, start in enumerate(crossings):
        sign = 1 if k % 2 == 0 else -1
        signs.append(sign)
        if k + 1 < len(crossings):
            length = crossings[k + 1] - start
            peak = GOLDEN_PEAKS[k + 1]
            counts.extend(
                round(sign * peak * math.sin(math.pi * j / length))
                for j in range(length)
            )
        else:
            # The final approach: a quarter sine that reaches the handover window and
            # keeps going, so no further crossing follows.
            length = round(0.445 / dt)
            counts.extend(
                round(
                    sign
                    * (GOLDEN_FINAL_APPROACH + 4)
                    * math.sin(0.5 * math.pi * j / length)
                )
                for j in range(length + 50)
            )
    return counts, crossings, signs


def _run_synthetic(params: FurutaParameters, counts: list[int]) -> tuple[KickLaw, int]:
    """Feed the golden-clock sequence to one loop; return it and the clock offset."""
    law = KickLaw(params, num_envs=1, dt=DT)
    offset = math.ceil(profile_duration(150, params) / DT)
    for k in range(offset + len(counts)):
        j = k - offset
        count = counts[j] if j >= 0 else 0
        law.step(torch.tensor([count]), k * DT)
    return law, offset


@pytest.mark.unit
def test_detector_fires_sixteen_kicks_against_the_swing(
    params: FurutaParameters,
) -> None:
    """On the golden swing the law fires the golden trace's sixteen in-loop kicks.

    Each is against the count velocity, alternating in sign, at the crossing sample or
    one sample after it depending on the crossing's direction.
    """
    counts, crossings, signs = _synthetic_counts()
    law, offset = _run_synthetic(params, counts)
    kicks = [row for row in law.log if row[1] > 0]
    assert len(kicks) == 16
    assert law.log[0][1] == 0 and law.log[0][4] == 150 and law.log[0][3] == FORWARD

    # Kick 1 fires on the first poll, which reads the initial deflection.
    assert kicks[0][3] == FORWARD
    assert round(kicks[0][2] / DT) - offset == 0

    for kick, crossing, sign in zip(kicks[1:], crossings, signs, strict=True):
        sample = round(kick[2] / DT) - offset
        # The crossing into a positive half swing is 0 after a negative count and is
        # seen on the zero; into a negative half swing it is seen one sample late.
        expected = crossing if sign > 0 else crossing + 1
        assert sample == expected
        velocity = counts[sample + 1] - counts[sample - 1]
        assert velocity * kick[3] < 0
        assert kick[3] == (BACKWARD if sign > 0 else FORWARD)

    directions = [kick[3] for kick in kicks]
    assert all(a == -b for a, b in zip(directions, directions[1:], strict=False))


@pytest.mark.unit
def test_detector_selects_amplitude_from_the_previous_half_swing(
    params: FurutaParameters,
) -> None:
    """With the stock amplitudes the bands are visible.

    Kicks 1 to 11 at 200, 12 to 16 at 130 once a 647-count swing has been seen, and
    120 selected after kick 16 from the 1020-count swing, never fired. The schedule is
    gated until more than four kicks have fired and reads the peak of the half swing
    before the one just kicked.
    """
    stock = replace(params, kick_microsteps=(200, 130, 120))
    counts, _, _ = _synthetic_counts()
    law, _ = _run_synthetic(stock, counts)
    amplitudes = [row[4] for row in law.log if row[1] > 0]
    assert amplitudes == [200] * 11 + [130] * 5
    assert law.amplitude.item() == 120
    assert law.stage_count.item() == 16


@pytest.mark.unit
def test_retuned_amplitudes_keep_every_fired_kick_at_200(
    params: FurutaParameters,
) -> None:
    """Every kick that fired on the golden trace was 200; 160 came after kick 16.

    The build the golden trace ran had stages 0 and 1 both at 200 and stage 2 at 160.
    """
    counts, _, _ = _synthetic_counts()
    law, _ = _run_synthetic(params, counts)
    assert [row[4] for row in law.log if row[1] > 0] == [200] * 16
    assert law.amplitude.item() == 160


@pytest.mark.unit
def test_loop_is_frozen_while_a_move_is_in_flight(params: FurutaParameters) -> None:
    """Crossings during a move are never seen, and the first count after it is read.

    After the first poll fires kick 1, the count is made to cross zero repeatedly
    inside the 185 ms move. The firmware is blocked in the driver for that time and
    sees none of it, so one kick fires, not several; the sample after the move is then
    read and, being smaller in magnitude than the first, registers the peak that flips
    the direction.
    """
    law = KickLaw(params, num_envs=1, dt=DT)
    offset = math.ceil(profile_duration(150, params) / DT)
    move_steps = math.ceil(profile_duration(200, params) / DT)
    flags = []
    # Alternating signs for the whole move, then a small negative count to be re-read.
    sequence = [-57] + [5 if j % 2 else -5 for j in range(move_steps - 1)] + [-20]
    for k in range(offset + len(sequence)):
        j = k - offset
        count = sequence[j] if j >= 0 else 0
        _, in_flight = law.step(torch.tensor([count]), k * DT)
        if j >= 0:
            flags.append(bool(in_flight[0]))
    assert law.kicks.item() == 1
    assert flags[0] is True
    assert sum(flags) == move_steps
    assert flags[-1] is False
    # The re-read registered a peak and the direction flipped for the next kick.
    assert law.direction.item() == BACKWARD
    assert bool(law.handled_peak[0])


@pytest.mark.unit
def test_zero_to_positive_is_not_a_crossing(params: FurutaParameters) -> None:
    """`(count ^ previous) < 0` is false from 0 to positive and true from 0 to negative.

    Two loops, both polled from a zero count. The one that goes positive never kicks;
    the one that goes negative kicks on its first non-zero sample.
    """
    law = KickLaw(params, num_envs=2, dt=DT)
    law.step(torch.tensor([0, 0]), 0.0)
    t = profile_duration(150, params) + DT
    law.step(torch.tensor([0, 0]), t)
    _, in_flight = law.step(torch.tensor([3, -3]), t + DT)
    assert law.kicks.tolist() == [0, 1]
    assert in_flight.tolist() == [False, True]


@pytest.mark.unit
def test_inactive_environments_hold_still(params: FurutaParameters) -> None:
    """An environment the caller has handed over neither polls nor moves."""
    law = KickLaw(params, num_envs=2, dt=DT)
    law.reset(position=torch.tensor([0.3, -0.3]))
    law.step(torch.tensor([0, 0]), 0.0)
    t = profile_duration(150, params) + DT
    active = torch.tensor([True, False])
    targets, in_flight = law.step(torch.tensor([-40, -40]), t, active=active)
    assert law.kicks.tolist() == [1, 0]
    assert in_flight.tolist() == [True, False]
    rest = -0.3 + 150 * params.rad_per_microstep
    assert targets[1].item() == pytest.approx(rest, abs=1e-6)


@pytest.mark.unit
def test_targets_follow_the_profile_from_the_rest_position(
    params: FurutaParameters,
) -> None:
    """The target is the rest angle plus the signed profile, one full move later.

    The initial move goes FORWARD from wherever the rotor started.
    """
    law = KickLaw(params, num_envs=1, dt=DT)
    law.reset(position=0.25)
    total = profile_duration(150, params)
    targets = []
    steps = math.ceil(total / DT) + 2
    for k in range(steps):
        target, _ = law.step(torch.tensor([0]), k * DT)
        targets.append(target.item())
    q = params.rad_per_microstep
    assert targets[0] == pytest.approx(
        0.25 + profile_displacement(torch.tensor(DT), 150, params).item(), abs=1e-6
    )
    assert targets[-1] == pytest.approx(0.25 + 150 * q, abs=1e-6)
    assert all(b >= a - 1e-7 for a, b in zip(targets, targets[1:], strict=False))


# The closed loop on the planar model.


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _swing_up_planar(
    params: FurutaParameters, model: PlanarModel, max_s: float = 25.0
) -> tuple[float | None, KickLaw, int | None]:
    """Run the law on the planar model from rest at hanging to 1 degree of upright.

    Returns the arrival time, the law, and the first count the loop read.

    The rotor acceleration the model integrates is the second difference of the
    commanded angle, the mean acceleration over each control step, which carries the
    profile's velocity steps at the start and end of every move as one-step impulses.
    """
    law = KickLaw(params, num_envs=1, dt=DT)
    theta, theta_dot = math.pi, 0.0
    previous = before = 0.0
    quantum = params.rad_per_encoder_count
    first_count = None
    for k in range(int(max_s / DT)):
        t = k * DT
        count = round(_wrap(theta + math.pi) / quantum)
        awake = bool(law.awake(t)[0])
        if awake and first_count is None:
            first_count = count
        if awake and abs(_wrap(theta)) < math.radians(1.0):
            return t, law, first_count
        target, _ = law.step(torch.tensor([count]), t)
        now = target.item()
        accel = (now - 2.0 * previous + before) / (DT * DT)
        theta, theta_dot = model.step(theta, theta_dot, accel, DT)
        before, previous = previous, now
    return None, law, first_count


@pytest.mark.unit
def test_planar_pendulum_reaches_upright_under_the_firmware_law(
    params: FurutaParameters,
) -> None:
    """From rest at hanging the planar pendulum reaches the 1 degree handover window.

    This is a coarse check and the tolerances say so. The planar equation carries the
    pivot's tangential push and nothing of the rotor's rate, so the centripetal and
    Coriolis terms of the two-link articulation are missing, and experiment 04 measured
    the consequence: the golden trace's own rotor motion, replayed open loop, does not
    climb in this model. Closed loop it does, because the detector times each kick to
    this pendulum rather than the real one. What survives the missing terms is the
    small-amplitude regime, where the law's timing can be checked against the board's:
    the first poll reads the initial move's deflection at 56 counts against the
    board's 57, and the first five in-loop kicks fall within 60 ms of the golden trace.
    Past that the swing widens, the missing terms grow with it, and the planar
    pendulum needs 21 kicks where the board needed 16; a band of 16 to 24 keeps the
    check meaningful (a double-firing detector or an amplitude a stage low would leave
    it) without pretending the model is the machine.
    """
    model = PlanarModel.from_parameters(params)
    arrival, law, first_count = _swing_up_planar(params, model)
    assert arrival is not None, "planar pendulum never reached upright"
    assert -75 <= first_count <= -40
    kicks = law.kicks.item()
    assert 16 <= kicks <= 24

    offset = profile_duration(150, params)
    times = [row[2] - offset for row in law.log if row[1] > 0]
    for simulated, golden in zip(times[:5], GOLDEN_KICKS_S[:5], strict=False):
        assert simulated == pytest.approx(golden, abs=0.06)
    signs = [row[3] for row in law.log if row[1] > 0]
    assert signs[0] == FORWARD
    assert all(a == -b for a, b in zip(signs, signs[1:], strict=False))

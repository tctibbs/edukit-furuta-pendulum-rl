"""Tests for the acceleration-command actuator.

These run on CPU tensors and need no simulator.
"""

import math

import pytest
import torch

from furuta.actuator import AccelerationCommandActuator
from furuta.parameters import FurutaParameters


@pytest.fixture
def params() -> FurutaParameters:
    """Parameters loaded from the project parameter file."""
    return FurutaParameters.from_yaml()


@pytest.fixture
def actuator(params: FurutaParameters) -> AccelerationCommandActuator:
    """A four-environment actuator on CPU."""
    return AccelerationCommandActuator(params, num_envs=4)


@pytest.mark.unit
def test_zero_action_does_not_move_the_rotor(
    actuator: AccelerationCommandActuator,
) -> None:
    """A zero command must leave the rotor exactly where it started."""
    for _ in range(100):
        pos = actuator.step(torch.zeros(4), dt=0.002)
    assert torch.allclose(pos, torch.zeros(4))


@pytest.mark.unit
def test_constant_acceleration_integrates_quadratically(
    actuator: AccelerationCommandActuator, params: FurutaParameters
) -> None:
    """A double integrator under constant acceleration gives 0.5*a*t^2.

    The window stays below the rate ceiling. At the acceleration limit of 11.78 rad/s^2
    (config/edukit.yaml, MAX_ACCEL in the supplied firmware) the rotor reaches the 19.6
    rad/s step-rate ceiling at 1.67 s, and after that position grows linearly. Semi-
    implicit integration carries an offset of half a step per step. The 2 percent
    tolerance admits that offset.
    """
    dt, steps = 0.002, 50
    for _ in range(steps):
        actuator.step(torch.ones(4), dt=dt)

    t = dt * steps
    expected = 0.5 * params.max_acceleration_rad_s2 * t**2
    assert actuator.position[0].item() == pytest.approx(expected, rel=0.02)


@pytest.mark.unit
def test_velocity_saturates_at_the_step_rate_ceiling(
    actuator: AccelerationCommandActuator,
) -> None:
    """Hardware cannot step faster than its ceiling, however long the command is held.

    The simulation runs in float32. The tolerance is sized to that precision.
    """
    for _ in range(10_000):
        actuator.step(torch.ones(4), dt=0.002)
    assert actuator.velocity.max().item() == pytest.approx(actuator.max_rate, rel=1e-6)


@pytest.mark.unit
def test_action_outside_the_range_is_clipped(
    actuator: AccelerationCommandActuator, params: FurutaParameters
) -> None:
    """A saturating policy must not command more than the motor can deliver."""
    actuator.step(torch.full((4,), 5.0), dt=0.002)
    reference = AccelerationCommandActuator(params, num_envs=4)
    reference.step(torch.ones(4), dt=0.002)
    assert torch.allclose(actuator.velocity, reference.velocity)


@pytest.mark.unit
def test_position_is_quantized_to_microsteps(
    actuator: AccelerationCommandActuator,
) -> None:
    """The reported position must always land on a whole microstep."""
    for _ in range(50):
        pos = actuator.step(torch.rand(4) * 2 - 1, dt=0.002)
        remainder = torch.remainder(pos, actuator.quantum)
        off_lattice = torch.minimum(remainder, actuator.quantum - remainder)
        # Float32 cannot land exactly on the lattice. The error grows with position.
        # The tolerance is a hundred-thousandth of a microstep.
        assert off_lattice.max().item() < actuator.quantum * 1e-5


@pytest.mark.unit
def test_quantization_hides_sub_microstep_motion(
    actuator: AccelerationCommandActuator,
) -> None:
    """Motion smaller than one microstep must not appear in the output at all.

    A policy that needs sub-microstep rotor positioning fails on hardware.
    """
    tiny = actuator.quantum / 10.0
    actuator.position += tiny
    assert torch.allclose(actuator.quantized_position(), torch.zeros(4))


@pytest.mark.unit
def test_reset_clears_only_the_selected_environments(
    actuator: AccelerationCommandActuator,
) -> None:
    """Resetting a subset must leave the other environments running."""
    for _ in range(10):
        actuator.step(torch.ones(4), dt=0.002)
    actuator.reset(torch.tensor([0, 2]))
    assert actuator.velocity[0].item() == 0.0
    assert actuator.velocity[2].item() == 0.0
    assert actuator.velocity[1].item() > 0.0


@pytest.mark.unit
def test_rate_ceiling_matches_the_documented_step_rate(
    params: FurutaParameters,
) -> None:
    """10000 microsteps/s at 3200 microsteps/rev is about 19.6 rad/s."""
    expected = 10_000 * (2 * math.pi / 3200)
    assert params.max_rotor_rate_rad_s == pytest.approx(expected)

"""Tests for the pivot dissipation torque.

These run on CPU tensors and need no simulator. The property under test is that the term
only ever removes energy. An explicitly applied Coulomb law injects energy near zero
velocity and at a coarse timestep.
"""

import math

import pytest
import torch

from furuta.dissipation import PivotDissipation
from furuta.parameters import FurutaParameters
from furuta.planar import PlanarModel


@pytest.fixture
def params() -> FurutaParameters:
    """Parameters loaded from the project parameter file."""
    return FurutaParameters.from_yaml()


@pytest.mark.unit
def test_no_torque_at_rest(params: FurutaParameters) -> None:
    """A motionless pivot gets zero torque rather than an arbitrarily signed one."""
    model = PivotDissipation(params)
    assert model.torque(torch.zeros(3), dt=0.001).abs().max().item() == 0.0


@pytest.mark.unit
def test_torque_opposes_motion(params: FurutaParameters) -> None:
    """The torque opposes the velocity in both directions."""
    model = PivotDissipation(params)
    vel = torch.tensor([2.0, -2.0, 9.0, -9.0])
    torque = model.torque(vel, dt=0.00025)
    assert torch.all(torque * vel < 0.0)


@pytest.mark.unit
def test_coulomb_cannot_reverse_the_joint(params: FurutaParameters) -> None:
    """The cap holds at any timestep: the bite never exceeds what stops the joint.

    Uncapped, a pivot creeping at 1e-4 rad/s takes a torque sized for a full swing and
    comes back faster the other way. That is energy in.
    """
    model = PivotDissipation(params)
    inertia = model.inertia
    for dt in (0.001, 0.00025, 0.01):
        vel = torch.tensor([1e-6, 1e-4, 1e-2, 1.0, 15.0])
        # vel / dt below is the deceleration that lands exactly on rest in one step.
        decel = model.torque(vel, dt).abs() / inertia
        assert torch.all(decel <= vel / dt + 1e-9)


@pytest.mark.unit
def test_zeroed_constants_are_inactive(params: FurutaParameters) -> None:
    """Zeroing both constants gives the pre-reconciliation plant.

    That is how the before and after runs come from one code path.
    """
    model = PivotDissipation(params, coulomb_deg_per_half_swing=0.0, drag_coeff=0.0)
    assert not model.active
    assert model.torque(torch.tensor([3.0, -3.0]), dt=0.001).abs().max().item() == 0.0


@pytest.mark.unit
def test_coefficients_match_the_planar_model(params: FurutaParameters) -> None:
    """The equation and the environment must derive the same coefficients.

    If they drift apart, the PhysX confirmation is checking a different plant than the
    one the equation fitted.
    """
    planar = PlanarModel.from_parameters(params)
    physx = PivotDissipation(params)
    assert physx.coulomb_rad_s2 == pytest.approx(planar.coulomb_rad_s2)
    assert physx.drag_coeff == pytest.approx(planar.drag_coeff)


@pytest.mark.unit
def test_drag_dominates_at_large_swing(params: FurutaParameters) -> None:
    """Past the crossover the quadratic term carries most of the loss.

    The reconciliation fitted this shape: Coulomb sets the small-amplitude bite and drag
    pulls the effective Q back down at large swings. At 14.7 rad/s, the speed through
    the bottom on the way to vertical, drag is the larger term.
    """
    model = PivotDissipation(params)
    speed = 14.7
    coulomb = model.coulomb_rad_s2
    drag = model.drag_coeff * speed * speed
    assert drag > coulomb


@pytest.mark.unit
def test_free_decay_loses_energy_monotonically(params: FurutaParameters) -> None:
    """Integrating the term alone can only take energy out.

    A hand-rolled pendulum carries the dissipation torque and no drive. Peak amplitude
    must fall every half cycle.
    """
    model = PivotDissipation(params)
    omega_g_squared = params.omega_g_squared
    dt = 0.00025
    theta, theta_dot = math.radians(150.0), 0.0
    peaks: list[float] = []
    previous = theta_dot
    for _ in range(int(20.0 / dt)):
        accel = -omega_g_squared * math.sin(theta)
        accel += model.torque(torch.tensor([theta_dot]), dt).item() / model.inertia
        theta_dot += accel * dt
        theta += theta_dot * dt
        if previous > 0.0 >= theta_dot:
            peaks.append(abs(theta))
        previous = theta_dot
    assert len(peaks) > 5
    assert all(b <= a + 1e-9 for a, b in zip(peaks, peaks[1:], strict=False))

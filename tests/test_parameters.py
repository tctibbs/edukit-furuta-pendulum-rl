"""Tests for the pendulum parameter derivation.

The derived inertia is checked against the manual's published constants. A failure means
the simulation's model disagrees with the manual it implements.
"""

import math

import pytest

from furuta.parameters import FurutaParameters


@pytest.fixture
def params() -> FurutaParameters:
    """Parameters loaded from the project parameter file."""
    return FurutaParameters.from_yaml()


@pytest.fixture
def manual_nominal(params: FurutaParameters) -> FurutaParameters:
    """The manual's nominal constants in place of this unit's measured values."""
    return FurutaParameters(
        **{
            **params.__dict__,
            "pendulum_length_m": 0.258,
            "rotor_arm_length_m": 0.140,
            "pendulum_mass_kg": 0.050,
            "normalized_shaft_inertia": 0.0139,
            "quality_factor": 20.0,
        }
    )


@pytest.mark.unit
def test_derivation_reproduces_the_manual(manual_nominal: FurutaParameters) -> None:
    """Manual App. D gives 55.85 (rad/s)^2 including the shaft inertia."""
    assert manual_nominal.omega_g_squared == pytest.approx(55.85, abs=0.01)


@pytest.mark.unit
def test_derivation_reproduces_the_manual_without_shaft(
    manual_nominal: FurutaParameters,
) -> None:
    """Manual App. D gives 57.01 (rad/s)^2 for the rod alone.

    The two published numbers differ only by the shaft term. Matching both fixes that
    term independently instead of letting it absorb error in 55.85.
    """
    bare = FurutaParameters(
        **{**manual_nominal.__dict__, "normalized_shaft_inertia": 0.0}
    )
    assert bare.omega_g_squared == pytest.approx(57.01, abs=0.01)


@pytest.mark.unit
def test_derivation_reproduces_the_manual_frequency(
    manual_nominal: FurutaParameters,
) -> None:
    """The manual measured 1.19 Hz on its reference unit."""
    assert manual_nominal.suspended_frequency_hz == pytest.approx(1.19, abs=0.005)


@pytest.mark.unit
def test_frequency_is_independent_of_mass(params: FurutaParameters) -> None:
    """Mass cancels from omega_g_squared."""
    heavier = FurutaParameters(**{**params.__dict__, "pendulum_mass_kg": 0.5})
    assert heavier.omega_g_squared == pytest.approx(params.omega_g_squared, rel=1e-12)


@pytest.mark.unit
def test_parallel_axis_is_consistent(params: FurutaParameters) -> None:
    """Pivot inertia must equal centre-of-mass inertia plus m*d^2."""
    d = params.pendulum_length_m / 2.0
    reconstructed = (
        params.pendulum_inertia_about_com_kg_m2 + params.pendulum_mass_kg * d**2
    )
    assert reconstructed == pytest.approx(params.pendulum_inertia_about_pivot_kg_m2)


@pytest.mark.unit
def test_microstep_resolution_matches_manual(params: FurutaParameters) -> None:
    """200 full steps at 1/16 microstepping is 3200 per revolution."""
    assert params.microsteps_per_rev == 3200
    assert params.rad_per_microstep == pytest.approx(2 * math.pi / 3200)


@pytest.mark.unit
def test_encoder_resolution_matches_manual(params: FurutaParameters) -> None:
    """2400 counts/rev is 0.15 degrees per count."""
    assert params.encoder_counts_per_rev == 2400
    assert math.degrees(params.rad_per_encoder_count) == pytest.approx(0.15)


@pytest.mark.unit
def test_decimation_is_an_integer(params: FurutaParameters) -> None:
    """Physics must be an integer multiple of the 500 Hz control loop."""
    assert params.decimation == 2
    assert params.control_dt_s == pytest.approx(0.002)


@pytest.mark.unit
def test_non_integer_decimation_is_rejected(params: FurutaParameters) -> None:
    """A rate pair that does not divide evenly raises ValueError."""
    bad = FurutaParameters(**{**params.__dict__, "physics_rate_hz": 750.0})
    with pytest.raises(ValueError, match="integer multiple"):
        _ = bad.decimation

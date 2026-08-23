"""Tests for the pendulum parameter derivation.

The derived inertia is checked against the manual's published constants. If these fail,
the simulation rests on a model that disagrees with the document it implements, which is
the failure mode most likely to look like success.
"""

import math

import pytest

from furuta.parameters import FurutaParameters


@pytest.fixture
def params() -> FurutaParameters:
    """Parameters loaded from the project parameter file."""
    return FurutaParameters.from_yaml()


@pytest.mark.unit
def test_derivation_reproduces_the_manual(params: FurutaParameters) -> None:
    """Manual App. D gives 55.85 (rad/s)^2 including the shaft inertia."""
    assert params.omega_g_squared == pytest.approx(55.85, abs=0.01)


@pytest.mark.unit
def test_derivation_reproduces_the_manual_without_shaft(
    params: FurutaParameters,
) -> None:
    """Manual App. D gives 57.01 (rad/s)^2 for the rod alone.

    Reproducing both published numbers shows the shaft term is understood and not
    fitted to hit the headline figure.
    """
    bare = FurutaParameters(**{**params.__dict__, "normalized_shaft_inertia": 0.0})
    assert bare.omega_g_squared == pytest.approx(57.01, abs=0.01)


@pytest.mark.unit
def test_derivation_reproduces_the_manual_frequency(
    params: FurutaParameters,
) -> None:
    """The manual measured 1.19 Hz on its reference unit."""
    assert params.suspended_frequency_hz == pytest.approx(1.19, abs=0.005)


@pytest.mark.unit
def test_frequency_is_independent_of_mass(params: FurutaParameters) -> None:
    """Mass cancels, so an unmeasured pendulum mass does not block the derivation."""
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
    """A rate pair that does not divide evenly is a silent phase error, so it raises."""
    bad = FurutaParameters(**{**params.__dict__, "physics_rate_hz": 750.0})
    with pytest.raises(ValueError, match="integer multiple"):
        _ = bad.decimation

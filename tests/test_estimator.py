"""Tests for the velocity slope estimator.

`board/observer.c` reimplements this estimator in C, so these pin the properties
that reimplementation has to reproduce: exactness on a ramp, the resolution it buys
over plain differencing, and the delay it costs.
"""

from __future__ import annotations

import math

import pytest
import torch

from furuta.estimator import VelocitySlopeEstimator, slope_coefficients

DT = 1.0 / 500.0


def _run(estimator: VelocitySlopeEstimator, samples: list[float]) -> list[float]:
    """Feed a single-environment sequence, returning the estimate after each sample."""
    return [estimator.update(torch.tensor([s])).item() for s in samples]


def test_coefficients_sum_to_zero_and_have_unit_slope_gain():
    """A constant signal must read zero rate, and a unit ramp must read unit rate."""
    for window in (2, 3, 8, 16):
        coeff = slope_coefficients(window, DT)
        assert coeff.sum().abs() < 1e-5
        ramp = torch.arange(window, dtype=torch.float32) * DT
        assert (ramp @ coeff).item() == pytest.approx(1.0, rel=1e-4)


def test_window_of_two_is_plain_differencing():
    """`window = 2` is the estimator the environment used before, exactly.

    This is what makes the ablation a config change: the same code path produces the
    old behaviour rather than a second implementation of it.
    """
    estimator = VelocitySlopeEstimator(window=2, dt=DT, num_envs=1, device="cpu")
    estimator.reset(None, torch.tensor([0.0]))
    samples = [0.0, 0.004, 0.011, 0.011, 0.02]
    got = _run(estimator, samples)
    previous = [0.0, *samples[:-1]]
    expected = [(b - a) / DT for a, b in zip(previous, samples, strict=True)]
    assert got == pytest.approx(expected, rel=1e-4)


def test_exact_on_a_noiseless_ramp():
    """A constant rate is recovered exactly once the window has filled."""
    rate = 3.7
    estimator = VelocitySlopeEstimator(window=16, dt=DT, num_envs=1, device="cpu")
    estimator.reset(None, torch.tensor([0.0]))
    got = _run(estimator, [rate * i * DT for i in range(1, 40)])
    assert got[-1] == pytest.approx(rate, rel=1e-4)


def test_quantization_noise_falls_against_plain_differencing():
    """The reason the estimator exists: resolution on a quantized ramp.

    A 2400-count encoder differenced over one 500 Hz period resolves 1.309 rad/s, which
    is larger than the whole recoverable velocity window at upright. A longer window
    averages the lattice out.
    """
    quantum = 2.0 * math.pi / 2400.0
    rate = 0.4
    samples = [round(rate * i * DT / quantum) * quantum for i in range(1, 200)]

    errors = {}
    for window in (2, 16):
        estimator = VelocitySlopeEstimator(
            window=window, dt=DT, num_envs=1, device="cpu"
        )
        estimator.reset(None, torch.tensor([0.0]))
        settled = _run(estimator, samples)[window + 20 :]
        errors[window] = max(abs(v - rate) for v in settled)

    # Plain differencing reads either zero or one whole quantum per period, so its worst
    # error is the gap between the lattice rate and the true one, and it exceeds the
    # signal being measured.
    assert errors[2] == pytest.approx(quantum / DT - rate, rel=1e-3)
    assert errors[2] > rate
    assert errors[16] < rate / 10.0


def test_group_delay_matches_the_stated_lag():
    """Delay is `(window - 1) / 2` samples, which bounds how long a window can be."""
    estimator = VelocitySlopeEstimator(window=16, dt=DT, num_envs=1, device="cpu")
    assert estimator.group_delay_s == pytest.approx(7.5 * DT)


def test_reset_seeds_flat_so_the_first_estimate_is_zero():
    """Seeding anywhere else injects a rate into the first observation of an episode."""
    estimator = VelocitySlopeEstimator(window=16, dt=DT, num_envs=2, device="cpu")
    start = torch.tensor([math.pi, -0.5])
    estimator.reset(None, start)
    assert torch.allclose(estimator.update(start), torch.zeros(2), atol=1e-6)


def test_wrapping_does_not_produce_a_spike():
    """Crossing pi must read as continuous motion, not a full-turn jump."""
    estimator = VelocitySlopeEstimator(window=4, dt=DT, num_envs=1, device="cpu")
    estimator.reset(None, torch.tensor([math.pi - 0.01]))
    step = 0.005
    got = _run(estimator, [math.pi - 0.01 + step * i for i in range(1, 12)])
    assert got[-1] == pytest.approx(step / DT, rel=1e-3)


def test_per_environment_reset_leaves_others_running():
    """Resetting one environment must not disturb the window of another."""
    estimator = VelocitySlopeEstimator(window=8, dt=DT, num_envs=2, device="cpu")
    estimator.reset(None, torch.zeros(2))
    for i in range(1, 20):
        estimator.update(torch.tensor([0.5 * i * DT, 0.5 * i * DT]))
    ids = torch.tensor([0])
    estimator.reset(ids, torch.tensor([0.0]))
    out = estimator.update(torch.tensor([0.0, 0.5 * 20 * DT]))
    assert out[0].item() == pytest.approx(0.0, abs=1e-6)
    assert out[1].item() == pytest.approx(0.5, rel=1e-3)


def test_window_below_two_is_rejected():
    """A single sample cannot carry a slope, so the degenerate case is an error."""
    with pytest.raises(ValueError, match="at least 2 samples"):
        slope_coefficients(1, DT)


def test_reset_with_a_rate_seeds_a_ramp_so_the_first_estimate_is_that_rate():
    """A moving reset must read its own rate at once, not a rate climbing from zero."""
    estimator = VelocitySlopeEstimator(16, DT, 1, "cpu")
    estimator.reset(None, torch.tensor([1.0]), torch.tensor([4.0]))
    # The next sample continues the motion; the window is then a clean ramp.
    first = estimator.update(torch.tensor([1.0 + 4.0 * DT])).item()
    assert abs(first - 4.0) < 1e-4
    # Flat seeding, the default, still reads zero for a body at rest.
    estimator.reset(None, torch.tensor([1.0]))
    assert abs(estimator.update(torch.tensor([1.0])).item()) < 1e-6


def test_reset_with_a_rate_is_per_environment():
    """Seeding one environment's ramp must not touch another's window."""
    estimator = VelocitySlopeEstimator(8, DT, 2, "cpu")
    estimator.reset(None, torch.zeros(2))
    for k in range(1, 9):
        estimator.update(torch.tensor([2.0 * k * DT, 0.0]))
    estimator.reset(torch.tensor([1]), torch.tensor([0.5]), torch.tensor([-3.0]))
    rates = estimator.update(torch.tensor([2.0 * 9 * DT, 0.5 - 3.0 * DT]))
    assert abs(rates[0].item() - 2.0) < 1e-4
    assert abs(rates[1].item() + 3.0) < 1e-4

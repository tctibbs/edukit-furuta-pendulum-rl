"""Velocity estimation from encoder-quantized angles.

The hardware has no velocity sensor, so rate has to be differenced from position.
Differencing two adjacent samples is the obvious way and it is the
expensive one: one encoder count over one control period is 1.309 rad/s of pendulum
rate and 0.982 rad/s of rotor rate, while the entire recoverable velocity window at
upright is 1.011 rad/s. The estimate therefore arrives in steps roughly as large as the
quantity being estimated, and a controller reading it saturates the actuator chasing
quantization noise.

A least-squares slope over a longer window trades delay for resolution. On a uniform
time grid the slope is a fixed FIR, so this is a dot product against precomputed
coefficients, and the window costs `(window - 1) / 2` samples of group delay. That delay
is the reason the window cannot simply be made large: at 500 Hz a 16-sample window lags
15 ms against the 136 ms unstable time constant of the pendulum. The same window at a
100 Hz control rate would lag 75 ms, over half the divergence it has to act inside.

`window = 2` reproduces plain adjacent-sample differencing exactly, which is what makes
the comparison a config change rather than a fork.

The firmware runs the same estimator: fixed window, fixed coefficients, a
ring buffer, and no allocation in the update path.

No Isaac Sim import, so this is unit-testable anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence

import torch


def slope_coefficients(window: int, dt: float) -> torch.Tensor:
    """Least-squares slope weights for `window` samples spaced `dt` apart.

    For samples `y_i` at times `t_i = i * dt`, the least-squares slope is
    `sum((t_i - t_bar) * y_i) / sum((t_i - t_bar)^2)`. Both sums are fixed once the
    window and the spacing are, so the estimate is a dot product.
    """
    if window < 2:
        raise ValueError(f"window must be at least 2 samples, got {window}")
    offsets = torch.arange(window, dtype=torch.float64) - (window - 1) / 2.0
    return (offsets / (dt * (offsets**2).sum())).to(torch.float32)


class VelocitySlopeEstimator:
    """Differences a quantized angle into a rate, one state per parallel environment.

    Angles are fed in as the sensor reports them. Wrapping is handled by accumulating
    increments, so the window never straddles a discontinuity at +/- pi.
    """

    def __init__(
        self,
        window: int,
        dt: float,
        num_envs: int,
        device: torch.device | str,
        *,
        wrap: bool = True,
    ) -> None:
        """Create estimator state for `num_envs` parallel environments."""
        self.window = window
        self.dt = dt
        self.wrap = wrap
        self._coeff = slope_coefficients(window, dt).to(device)
        # Running unwrapped angle, and the last `window` values of it.
        self._unwrapped = torch.zeros(num_envs, device=device)
        self._buffer = torch.zeros(num_envs, window, device=device)
        self._previous = torch.zeros(num_envs, device=device)

    @property
    def group_delay_s(self) -> float:
        """Lag of the estimate behind the true rate, for a constant acceleration."""
        return (self.window - 1) / 2.0 * self.dt

    def reset(
        self,
        env_ids: Sequence[int] | torch.Tensor | None,
        angle: torch.Tensor,
        rate: torch.Tensor | float = 0.0,
    ) -> None:
        """Seed the filter window with linear historical states for `angle` and `rate`.

        Constructs a linear ramp ending at `angle` with slope `rate` so the initial
        filter output matches `rate` without 32 ms ramp-up delay. `angle` should be
        pre-quantized to match the next differenced encoder reading.
        """
        if not isinstance(rate, torch.Tensor):
            rate = torch.full_like(angle, float(rate))
        # Sample k of the window is (window - 1 - k) periods before `angle`.
        lags = torch.arange(
            self.window - 1, -1, -1, device=angle.device, dtype=angle.dtype
        )
        history = angle.unsqueeze(-1) - rate.unsqueeze(-1) * lags * self.dt
        if env_ids is None:
            self._unwrapped = angle.clone()
            self._previous = angle.clone()
            self._buffer = history.clone()
        else:
            self._unwrapped[env_ids] = angle
            self._previous[env_ids] = angle
            self._buffer[env_ids] = history

    def update(self, angle: torch.Tensor) -> torch.Tensor:
        """Push one sample and return the estimated rate."""
        delta = angle - self._previous
        if self.wrap:
            delta = torch.atan2(torch.sin(delta), torch.cos(delta))
        self._previous = angle
        self._unwrapped = self._unwrapped + delta

        self._buffer = torch.roll(self._buffer, -1, dims=1)
        self._buffer[:, -1] = self._unwrapped
        return self._buffer @ self._coeff

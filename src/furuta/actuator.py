"""Acceleration-command actuator for the Edukit rotor.

It re-creates the firmware's `apply_acceleration()` from the listing in the Edukit
Manual, App. E, page 160. The rotor is a stepper driven in acceleration. The plant
from action to rotor angle is a double integrator. In firmware order, the model
saturates acceleration, saturates step rate, and quantizes position to whole
microsteps.
"""

from __future__ import annotations

import torch

from furuta.parameters import FurutaParameters


class AccelerationCommandActuator:
    """Integrates an acceleration command into a quantized rotor position.

    Holds one state per parallel environment. The caller drives the result onto the
    rotor joint.
    """

    def __init__(
        self,
        params: FurutaParameters,
        num_envs: int,
        device: str | torch.device = "cpu",
    ) -> None:
        """Create rotor state for `num_envs` parallel environments."""
        self._p = params
        self._device = torch.device(device)
        self.position = torch.zeros(num_envs, device=self._device)
        self.velocity = torch.zeros(num_envs, device=self._device)

    @property
    def max_acceleration(self) -> float:
        """Acceleration limit in rad/s^2, bounded by motor torque."""
        return self._p.max_acceleration_rad_s2

    @property
    def max_rate(self) -> float:
        """Rotor speed ceiling in rad/s, from the step-rate limit."""
        return self._p.max_rotor_rate_rad_s

    @property
    def quantum(self) -> float:
        """One microstep in radians, the rotor position quantum."""
        return self._p.rad_per_microstep

    def reset(self, env_ids: torch.Tensor | None = None) -> None:
        """Zero the rotor state, for all environments or a subset."""
        if env_ids is None:
            self.position[:] = 0.0
            self.velocity[:] = 0.0
        else:
            self.position[env_ids] = 0.0
            self.velocity[env_ids] = 0.0

    def step(self, action: torch.Tensor, dt: float) -> torch.Tensor:
        """Advance the rotor one control period, returning the quantized position.

        `action` is normalized to [-1, 1] and scaled to the acceleration limit. Values
        outside that range are clipped.
        """
        accel = torch.clamp(action, -1.0, 1.0) * self.max_acceleration

        # Semi-implicit: velocity first, then position from the new velocity. Matches a
        # firmware loop that updates the step rate and then emits steps at it.
        self.velocity = torch.clamp(
            self.velocity + accel * dt, -self.max_rate, self.max_rate
        )
        self.position = self.position + self.velocity * dt

        return self.quantized_position()

    def quantized_position(self) -> torch.Tensor:
        """Rotor position rounded to whole microsteps."""
        return torch.round(self.position / self.quantum) * self.quantum

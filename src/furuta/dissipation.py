"""Dry friction and quadratic drag on the pendulum pivot, as a joint torque.

Isaac Lab's `ImplicitActuatorCfg` expresses `K(target - q) - D*qdot` and nothing else,
so the drive carries the viscous term and neither of the other two. The Coulomb bite
and the velocity-squared drag that Experiment 04 fitted have to be applied as a
feed-forward torque on the pivot, once per physics substep.

The planar model (`src/furuta/planar.py`) states both as angular accelerations:

    theta'' -= c_dry * sign(theta') + b_drag * |theta'| * theta'

so the torque is those multiplied by the pendulum's inertia about its pivot. The
equation and the environment read the same two constants from `config/edukit.yaml`.

Nothing here imports Isaac Sim. The law is unit tested on any machine.
"""

from __future__ import annotations

import math

import torch

from furuta.parameters import FurutaParameters


class PivotDissipation:
    """Coulomb and quadratic-drag torque for the pendulum pivot.

    With both constants zero `torque` returns zeros, leaving viscous damping alone on
    the drive. The before and after runs come from one code path that way.
    """

    def __init__(
        self,
        params: FurutaParameters,
        coulomb_deg_per_half_swing: float | None = None,
        drag_coeff: float | None = None,
    ) -> None:
        """Derive the two coefficients, defaulting to the reconciled config values."""
        coulomb_deg = (
            params.coulomb_loss_deg_per_half_swing
            if coulomb_deg_per_half_swing is None
            else coulomb_deg_per_half_swing
        )
        drag = params.quadratic_drag_coeff if drag_coeff is None else drag_coeff

        # A linear amplitude decay of `delta` per half cycle is 2c/omega_g^2 of Coulomb
        # deceleration. `PlanarModel.from_parameters` derives it the same way, and a
        # unit test pins both simulations to the same number.
        self.coulomb_rad_s2 = math.radians(coulomb_deg) * params.omega_g_squared / 2.0
        self.drag_coeff = drag
        self.inertia = params.pendulum_inertia_about_pivot_kg_m2

    @property
    def active(self) -> bool:
        """Whether either term is non-zero. A caller with neither can skip the write."""
        return self.coulomb_rad_s2 != 0.0 or self.drag_coeff != 0.0

    def torque(self, joint_vel: torch.Tensor, dt: float) -> torch.Tensor:
        """Dissipative torque in N m, opposing `joint_vel`, for one substep of `dt`.

        The Coulomb magnitude is capped at the deceleration that would bring the joint
        exactly to rest within the substep. Without the cap a pivot near rest
        alternates full-magnitude torque each step and pumps energy in rather than
        out. `planar.py` carries the same cap.
        """
        speed = torch.abs(joint_vel)
        coulomb = torch.clamp(
            torch.full_like(speed, self.coulomb_rad_s2), max=speed / dt
        )
        accel = coulomb + self.drag_coeff * speed * speed
        # `sign` is zero at exactly zero velocity. A motionless pivot then gets no
        # torque at all rather than one in an arbitrary direction.
        return -self.inertia * accel * torch.sign(joint_vel)

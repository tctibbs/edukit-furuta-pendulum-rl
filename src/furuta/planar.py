"""The validated planar Furuta model, as an importable stdlib module.

Geometry and damping come from `parameters.py`, and the rest is a one-step integrator
with no Isaac Sim import. The trace replay in `trace.py` drives the model with
the rotor motion a swing-up took and asks whether its pendulum lands where the real one
did.

Angles are measured from upright: theta = 0 is balanced, theta = +/- pi is hanging. The
pendulum equation is

    theta'' = omega_g^2 sin(theta)                 gravity (destabilising near upright)
            + coupling * rotor_accel * cos(theta)   the rotor's push
            + kappa * rotor_rate^2 sin(theta) cos(theta)   the arm's spin, optional
            - (omega_g / Q) * theta'                viscous damping
            - c_dry * sign(theta')                  dry (Coulomb) friction
            - b_drag * |theta'| * theta'            large-amplitude (quadratic) drag

Experiment 04 fitted the Coulomb bite and the drag coefficient against the
full-amplitude ring-down, and `config/edukit.yaml` carries both.

The arm-rate term is the one the manual's planar model drops. A pendulum on a turning
arm is flung toward horizontal: near the top the term adds to gravity's destabilising
stiffness and near the bottom it subtracts from the restoring one, `omega_g^2 - kappa *
rotor_rate^2`. The hanging pendulum lifts on its own once the arm turns faster than
`omega_g / sqrt(kappa)`, 7.45 rad/s here. `kappa` is the rod's inertia about the pivot
over the whole pivot inertia, 0.974 with the measured shaft term. The shaft's inertia
is symmetric about the pivot axis and takes no part in the fling. Callers that do not
pass `rotor_rate` get the manual's model unchanged. The trace replay and the
free-swing fits were validated against that form.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from furuta.parameters import FurutaParameters


@dataclass(frozen=True)
class PlanarModel:
    """Planar Furuta pendulum, driven by a commanded or measured rotor acceleration."""

    omega_g_squared: float
    omega_g: float
    coupling: float
    quality_factor: float
    coulomb_rad_s2: float
    drag_coeff: float = 0.0
    centrifugal: float = 0.0
    """`kappa` above; zero leaves the arm's spin out, as the manual's model does."""

    @classmethod
    def from_parameters(cls, params: FurutaParameters | None = None) -> PlanarModel:
        """Build from the reconciled constants, defaulting to the parameter file."""
        p = params or FurutaParameters.from_yaml()
        omega_g_squared = p.omega_g_squared
        inertia_factor = 2.0 / 3.0 + p.normalized_shaft_inertia
        coupling = p.rotor_arm_length_m / (p.pendulum_length_m * inertia_factor)
        # A linear amplitude decay of delta per half cycle is 2c/omega_g^2 of Coulomb
        # deceleration.
        coulomb_deg = p.coulomb_loss_deg_per_half_swing
        coulomb = math.radians(coulomb_deg) * omega_g_squared / 2.0
        # The rod's share of the pivot inertia, 1/3 against 1/3 plus half the manual's
        # normalised shaft term.
        centrifugal = (1.0 / 3.0) / inertia_factor * 2.0
        return cls(
            omega_g_squared=omega_g_squared,
            omega_g=math.sqrt(omega_g_squared),
            coupling=coupling,
            quality_factor=p.quality_factor,
            coulomb_rad_s2=coulomb,
            drag_coeff=p.quadratic_drag_coeff,
            centrifugal=centrifugal,
        )

    def step(
        self,
        theta: float,
        theta_dot: float,
        rotor_accel: float,
        dt: float,
        substeps: int = 4,
        rotor_rate: float = 0.0,
    ) -> tuple[float, float]:
        """Advance (theta, theta_dot) by one control step under a rotor acceleration.

        Semi-implicit Euler over `substeps`. The Coulomb term is capped so it can
        remove the remaining speed but never reverse it inside a substep. `rotor_rate`
        is the arm's speed over the step, for the centrifugal term.
        """
        h = dt / substeps
        spin = self.centrifugal * rotor_rate * rotor_rate
        for _ in range(substeps):
            accel = (
                self.omega_g_squared * math.sin(theta)
                + self.coupling * rotor_accel * math.cos(theta)
                + spin * math.sin(theta) * math.cos(theta)
                - (self.omega_g / self.quality_factor) * theta_dot
            )
            if abs(theta_dot) > 1e-9:
                coulomb = min(self.coulomb_rad_s2, abs(theta_dot) / h)
                accel -= math.copysign(coulomb, theta_dot)
                accel -= self.drag_coeff * abs(theta_dot) * theta_dot
            theta_dot += accel * h
            theta += theta_dot * h
        return theta, theta_dot

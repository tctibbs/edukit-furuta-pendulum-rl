"""Physical parameters for the Edukit pendulum, loaded from the parameter file.

The model is the manual's linearized Furuta pendulum (App. D, Pendulum Dynamics).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "edukit.yaml"


def gravity_for_tilt(tilt_deg: float, gravity: float) -> tuple[float, float, float]:
    """Gravity in the base frame for a baseplate rolled by `tilt_deg` about X.

    Rolling the base and tilting gravity against it are the same dynamics, and gravity
    is a scene setting where the roll would be a change to the asset. With the base
    rolled by alpha, gravity in base coordinates is `(0, -g sin alpha, -g cos alpha)`.

    The pivot axis lies along the arm, so the tilt appears as a sinusoid in rotor angle
    rather than a constant offset: at rotor angle phi the hanging equilibrium sits at
    `-alpha * cos(phi)`, amplitude alpha. Experiment 03's full-circle sweep measured
    that sinusoid.
    """
    alpha = math.radians(tilt_deg)
    return (0.0, -gravity * math.sin(alpha), -gravity * math.cos(alpha))


@dataclass(frozen=True)
class FurutaParameters:
    """Physical and interface constants, with derived quantities as properties.

    SI throughout, angles in radians.
    """

    pendulum_length_m: float
    rotor_arm_length_m: float
    pendulum_mass_kg: float
    gravity_m_s2: float
    normalized_shaft_inertia: float
    quality_factor: float
    full_steps_per_rev: int
    microsteps_per_full_step: int
    max_step_rate_hz: float
    max_acceleration_rad_s2: float
    loop_rate_hz: float
    physics_rate_hz: float
    encoder_counts_per_rev: int
    # Fitted by the reconciliation experiment against the full-amplitude ring-down.
    # Defaults keep older parameter files loading.
    coulomb_loss_deg_per_half_swing: float = 0.0
    friction_crossover_deg: float = 0.0
    quadratic_drag_coeff: float = 0.0
    # The L6474 position-move profile the swing-up's kicks run on, and the balance
    # path's own clamp. Provenance in config/edukit.yaml; defaults keep older
    # configuration files loading.
    profile_min_speed_rad_s: float = 1.571
    profile_max_speed_rad_s: float = 3.927
    kick_microsteps: tuple[int, int, int] = (200, 200, 160)

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> FurutaParameters:
        """Load parameters from the project parameter file."""
        path = Path(path) if path is not None else DEFAULT_CONFIG
        raw: dict[str, Any] = yaml.safe_load(path.read_text())
        return cls(
            **raw["geometry"],
            **raw["dynamics"],
            **raw["actuator"],
            **raw["control"],
            **raw["sensing"],
        )

    # Inertia.

    @property
    def shaft_inertia_kg_m2(self) -> float:
        """Inertia of the parts that turn with the pendulum, besides the rod.

        The manual publishes it normalized, as 2*I_shaft/(m*L^2).
        """
        half = self.normalized_shaft_inertia / 2.0
        return half * self.pendulum_mass_kg * self.pendulum_length_m**2

    @property
    def pendulum_inertia_about_pivot_kg_m2(self) -> float:
        """Total inertia of the pendulum assembly about its pivot.

        The rod is (1/3) m L^2 about its end, plus the shaft term. The shaft term
        lowers the suspended mode from 57.01 to 55.85 (rad/s)^2 on the manual's nominal
        constants. On this unit's measured length and fitted shaft inertia the pair is
        55.51 and 54.04.
        """
        rod = self.pendulum_mass_kg * self.pendulum_length_m**2 / 3.0
        return rod + self.shaft_inertia_kg_m2

    @property
    def pendulum_inertia_about_com_kg_m2(self) -> float:
        """Inertia about the centre of mass, the form PhysX takes.

        Parallel axis theorem, with the centre of mass at L/2 from the pivot.
        """
        offset = self.pendulum_mass_kg * (self.pendulum_length_m / 2.0) ** 2
        return self.pendulum_inertia_about_pivot_kg_m2 - offset

    # Dynamics.

    @property
    def omega_g_squared(self) -> float:
        """Suspended-mode natural frequency squared, in (rad/s)^2.

        Gravity torque per radian of swing, over pivot inertia. Manual App. D gives
        55.85 with the shaft term and 57.01 without.
        """
        torque = (
            self.pendulum_mass_kg * self.gravity_m_s2 * self.pendulum_length_m / 2.0
        )
        return torque / self.pendulum_inertia_about_pivot_kg_m2

    @property
    def suspended_frequency_hz(self) -> float:
        """Free-swing frequency of the hanging pendulum. The manual gives 1.19 Hz."""
        return math.sqrt(self.omega_g_squared) / (2.0 * math.pi)

    @property
    def pivot_damping_n_m_s(self) -> float:
        """Pivot damping implied by the quality factor.

        A linear damper of c = I * omega / Q reproduces a given Q for a second-order
        system.
        """
        omega = math.sqrt(self.omega_g_squared)
        return self.pendulum_inertia_about_pivot_kg_m2 * omega / self.quality_factor

    # Actuator quantization.

    @property
    def microsteps_per_rev(self) -> int:
        """Microsteps in one rotor revolution. 200 full steps at 1/16 gives 3200."""
        return self.full_steps_per_rev * self.microsteps_per_full_step

    @property
    def rad_per_microstep(self) -> float:
        """One microstep in radians, the rotor's position resolution."""
        return 2.0 * math.pi / self.microsteps_per_rev

    @property
    def rad_per_encoder_count(self) -> float:
        """Pendulum angle resolution, 2400 counts/rev."""
        return 2.0 * math.pi / self.encoder_counts_per_rev

    @property
    def max_rotor_rate_rad_s(self) -> float:
        """Rotor speed ceiling implied by the step-rate ceiling."""
        return self.max_step_rate_hz * self.rad_per_microstep

    # Rates.

    @property
    def decimation(self) -> int:
        """Physics steps per policy step. Must be an integer."""
        ratio = self.physics_rate_hz / self.loop_rate_hz
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError(
                f"physics_rate_hz ({self.physics_rate_hz}) must be an integer multiple "
                f"of loop_rate_hz ({self.loop_rate_hz}), got ratio {ratio}"
            )
        return int(round(ratio))

    @property
    def physics_dt_s(self) -> float:
        """Physics timestep in seconds."""
        return 1.0 / self.physics_rate_hz

    @property
    def control_dt_s(self) -> float:
        """Control period in seconds. 2 ms at the hardware's 500 Hz loop."""
        return 1.0 / self.loop_rate_hz

    @property
    def stiction_hold_angle_rad(self) -> float:
        """Half the Coulomb loss in radians, the angle stiction can hold against.

        `c` is `radians(delta) * omega_g^2 / 2` for a loss of `delta` per half swing, so
        the hold angle is `radians(delta) / 2`. `omega_g^2` cancels and no other
        constant enters. Inside it the encoder reports an angle no controller can act
        on.
        """
        return math.radians(self.coulomb_loss_deg_per_half_swing) / 2.0

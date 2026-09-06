"""Shared reconciliation core for experiment 04.

Drives the planar model through the excitations the hardware probes ran and feeds the
result through the same analysis code the captures go through (`furuta.pump`,
`furuta.trace`). The figure scripts import this instead of each carrying a harness.

The model states compared here, both at the refit geometry from experiment 03:

    before : the env as it entered experiment 04, purely viscous (no Coulomb, no drag)
    after  : the reconciled model, viscous + Coulomb + quadratic drag (from config)

The hardware side is distilled out of the raw captures once by
`scripts/distill_captures.py` and read back from a CSV by `_datasets.py`. That keeps the
multi-megabyte traces out of a redraw.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "src"))

from _datasets import binned_median as _binned_median  # noqa: E402

from furuta.freeswing import Trace  # noqa: E402
from furuta.parameters import FurutaParameters  # noqa: E402
from furuta.planar import PlanarModel  # noqa: E402
from furuta.pump import RingdownSegment, qeff_vs_amplitude  # noqa: E402

# Read from the one place the reconciled dissipation is defined.
_P = FurutaParameters.from_yaml()
AFTER_COULOMB_DEG = _P.coulomb_loss_deg_per_half_swing
AFTER_DRAG = _P.quadratic_drag_coeff

# The sim analogue of a mode d capture: one held release per target amplitude.
LADDER_DEG = (162, 135, 108, 82, 58, 38, 22)


def planar_model(coulomb_deg: float, drag: float) -> PlanarModel:
    """The planar model at the refit geometry, with the loss terms the caller gives."""
    og2 = _P.omega_g_squared
    coupling = _P.rotor_arm_length_m / (
        _P.pendulum_length_m * (2.0 / 3.0 + _P.normalized_shaft_inertia)
    )
    return PlanarModel(
        omega_g_squared=og2,
        omega_g=math.sqrt(og2),
        coupling=coupling,
        quality_factor=_P.quality_factor,
        coulomb_rad_s2=math.radians(coulomb_deg) * og2 / 2.0,
        drag_coeff=drag,
    )


# Rotor acceleration used to pump each rung, in rad/s^2. Large enough to climb to the
# top rung against the fitted losses, small enough that the cut below lands before the
# pendulum carries over the top.
PUMP_ACCEL = 12.0


def sim_qeff(
    coulomb_deg: float, drag: float, dt: float = 0.002, secs: float = 46.0
) -> list[tuple[float, float]]:
    """Effective Q versus amplitude from a simulated ring-down ladder.

    Each decay goes through `pump.qeff_vs_amplitude`, the same function a hardware
    decay goes through.

    Each rung is pumped up to its amplitude and then released, which is what mode d does
    on the bench. Starting at rest at the rung instead would hide its own turning point:
    a peak detector needs samples either side of a maximum, and the first sample of a
    release has nothing before it. The first peak it could see is a half swing down,
    which from the top rung is 33 degrees, and the simulated curve then stops short of
    the measured one for a reason that lives entirely in the analysis.
    """
    model = planar_model(coulomb_deg, drag)
    omega_g_squared = model.omega_g_squared
    pairs: list[tuple[float, float]] = []
    for a0 in LADDER_DEG:
        theta, theta_dot = math.pi, 0.02
        driving = True
        cut = 0
        times: list[float] = []
        angle: list[float] = []
        for i in range(int(secs / dt)):
            times.append(i * dt)
            angle.append(math.degrees(theta - math.pi))
            if driving:
                # Where a free coast would turn, from energy alone. Cutting on the
                # predicted turning point rather than the current angle keeps the
                # low-loss plant from carrying over the top.
                cosine = math.cos(theta) + theta_dot**2 / (2.0 * omega_g_squared)
                turn = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
                if cosine <= 1.0 and 180.0 - abs(turn) >= a0:
                    driving = False
                    cut = i
            accel = 0.0
            if driving:
                accel = PUMP_ACCEL * (1.0 if theta_dot * math.cos(theta) > 0 else -1.0)
            theta, theta_dot = model.step(theta, theta_dot, accel, dt)
        # Analyse only what follows the cut. While the drive is still adding energy the
        # amplitude barely changes between peaks, and `pi / loss` reports a Q in the
        # hundreds. Mode d keeps the two apart with its drive-state column; here the
        # index is known exactly.
        segment = RingdownSegment(
            float(a0),
            Trace(tuple(times[cut:]), tuple(angle[cut:]), 6.666667),
        )
        pairs.extend(qeff_vs_amplitude(segment))
    return pairs


# Kept for anything that still imports `binned_median` from this module.
binned_median = _binned_median

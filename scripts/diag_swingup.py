# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "pyyaml"]
# ///
"""Is swing-up inside the rotor travel bound feasible at all, for any controller?

A pump that works by bang-bang can walk the arm into the travel termination before the
swing reaches vertical. Either the bound forbids the task, or it only forbids that
strategy. This script settles which, by running scripted controllers against the
planar model (Manual App. D, constants from `config/edukit.yaml` except the friction,
Experiment 03's 1.07 degree Coulomb loss with no drag term) under the
configured actuator clamps, with no Isaac Sim and no GPU.

Three controllers:

- A pure bang-bang pump, `u = a_max * sign(theta_dot * cos(theta))`, the textbook
  swing-up.
- The same pump behind a travel governor: when the arm's stopping distance at full
  braking would carry it past the allowance, brake instead.
- LQR capture near vertical, entered inside the recoverable set implied by the
  11.78 rad/s^2 acceleration bound. It must then hold the pendulum for 5 s within 3
  degrees of vertical.

Limitations: the model is the manual's planar one, which drops the rotor-rate coupling
terms the full rigid-body asset carries, and the controllers read true state where a
policy reads quantized 500 Hz finite differences.
The answer is an existence proof about the plant, not a promise about the learner.

Runs on the workstation:

    uv run scripts/diag_swingup.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from scipy.linalg import solve_continuous_are

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from furuta.parameters import FurutaParameters  # noqa: E402

PARAMS = FurutaParameters.from_yaml()
OMEGA_G_SQ = PARAMS.omega_g_squared
OMEGA_G = math.sqrt(OMEGA_G_SQ)
INERTIA_FACTOR = 2.0 / 3.0 + PARAMS.normalized_shaft_inertia
COUPLING = PARAMS.rotor_arm_length_m / (PARAMS.pendulum_length_m * INERTIA_FACTOR)
A_MAX = PARAMS.max_acceleration_rad_s2
V_MAX = PARAMS.max_rotor_rate_rad_s
CONTROL_DT = PARAMS.control_dt_s
SUBSTEPS = 4
H = CONTROL_DT / SUBSTEPS

# Coulomb deceleration from Experiment 03's 1.07 degree small-swing loss per half swing,
# not the 0.65 config/edukit.yaml now holds with its drag term:
# a linear amplitude decay of delta per half swing is 2c/omega_g^2.
C_DRY = math.radians(1.07) * OMEGA_G_SQ / 2.0

# Capture gains: the LQR weights scripts/scripted_swingup.py uses for its benchmark.
_A = np.array(
    [
        [0, 1, 0, 0],
        [OMEGA_G_SQ, -OMEGA_G / PARAMS.quality_factor, 0, 0],
        [0, 0, 0, 1],
        [0, 0, 0, 0],
    ]
)
_B = np.array([[0.0], [COUPLING], [0.0], [1.0]])
_P = solve_continuous_are(_A, _B, np.diag([100.0, 1.0, 1.0, 0.1]), [[1.0]])
LQR_GAIN = (_B.T @ _P).ravel()


def step_plant(state: np.ndarray, accel_cmd: float) -> np.ndarray:
    """Advance [theta, theta_dot, phi, phi_dot] one control step, theta from upright."""
    theta, theta_dot, phi, phi_dot = state
    for _ in range(SUBSTEPS):
        accel = (
            OMEGA_G_SQ * math.sin(theta)
            + COUPLING * accel_cmd * math.cos(theta)
            - (OMEGA_G / PARAMS.quality_factor) * theta_dot
        )
        if abs(theta_dot) > 1e-9:
            accel -= math.copysign(min(C_DRY, abs(theta_dot) / H), theta_dot)
        theta_dot += accel * H
        theta += theta_dot * H
        phi_dot_next = phi_dot + accel_cmd * H
        if abs(phi_dot_next) > V_MAX:
            phi_dot_next = math.copysign(V_MAX, phi_dot_next)
        phi += 0.5 * (phi_dot + phi_dot_next) * H
        phi_dot = phi_dot_next
    return np.array([theta, theta_dot, phi, phi_dot])


def run(allowance: float, governed: bool, duration_s: float = 40.0) -> dict:
    """Swing up from hanging at rest; report arrival, travel, and the 5 s hold."""
    state = np.array([math.pi, 0.0, 0.0, 0.0])
    capturing = False
    peak_pump = peak_total = 0.0
    t_arrive = arrive_rate = None
    held_steps = 0
    for k in range(int(duration_s / CONTROL_DT)):
        theta = math.atan2(math.sin(state[0]), math.cos(state[0]))
        theta_dot, phi, phi_dot = state[1], state[2], state[3]
        if not capturing:
            u = A_MAX * (1.0 if theta_dot * math.cos(theta) >= 0 else -1.0)
            if governed:
                stop_dist = phi_dot * phi_dot / (2.0 * A_MAX)
                if phi_dot > 0 and phi + stop_dist >= allowance * 0.95:
                    u = -A_MAX
                elif phi_dot < 0 and phi - stop_dist <= -allowance * 0.95:
                    u = A_MAX
            if abs(theta) < 0.35 and abs(theta_dot + 7.351 * theta) < 1.011:
                capturing = True
                t_arrive, arrive_rate = k * CONTROL_DT, theta_dot
        if capturing:
            feedback = -LQR_GAIN @ np.array([theta, theta_dot, phi, phi_dot])
            u = float(np.clip(feedback, -A_MAX, A_MAX))
            held_steps = held_steps + 1 if abs(theta) < math.radians(3.0) else 0
        state = step_plant(state, u)
        peak_total = max(peak_total, abs(state[2]))
        if not capturing:
            peak_pump = peak_total
        if held_steps * CONTROL_DT >= 5.0:
            return {
                "up": True,
                "t": t_arrive,
                "pump": peak_pump,
                "total": peak_total,
                "rate": arrive_rate,
                "held": True,
            }
    return {
        "up": t_arrive is not None,
        "t": t_arrive,
        "pump": peak_pump,
        "total": peak_total,
        "rate": arrive_rate,
        "held": False,
    }


def main() -> int:
    """Print the feasibility table."""
    # Check the model first. Its small-swing period should match 2*pi/omega_g.
    state = np.array([math.pi - 0.1, 0.0, 0.0, 0.0])
    crossings = []
    for k in range(int(4.0 / CONTROL_DT)):
        previous = state[0]
        state = step_plant(state, 0.0)
        if previous < math.pi <= state[0]:
            crossings.append(k * CONTROL_DT)
    period = crossings[1] - crossings[0]
    print(
        f"model check: small-swing period {period:.3f} s against 2*pi/omega_g ="
        f" {2 * math.pi / OMEGA_G:.3f} s, separatrix rate {2 * OMEGA_G:.2f} rad/s"
    )

    result = run(allowance=math.inf, governed=False)
    print(
        f"\npure bang-bang pump, travel unlimited: arrives at {result['t']:.2f} s"
        f" after {result['pump']:.1f} rad of arm travel"
    )

    print("\ngoverned pump, then LQR capture and a 5 s hold inside 3 degrees:")
    print("  allowance   arrives      arrival rate   pump travel   peak travel   held")
    for allowance in (math.pi, 2.0, math.pi / 2, 1.0, 0.5, 0.35):
        result = run(allowance=allowance, governed=True)
        if result["up"]:
            print(
                f"  {allowance:6.3f} rad  {result['t']:6.2f} s"
                f"  {result['rate']:+10.2f} rad/s"
                f"  {result['pump']:8.2f} rad {result['total']:10.2f} rad"
                f"   {'yes' if result['held'] else 'no'}"
            )
        else:
            print(
                f"  {allowance:6.3f} rad   never arrives"
                f"  {'':10s}{result['pump']:8.2f} rad {result['total']:10.2f} rad   no"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

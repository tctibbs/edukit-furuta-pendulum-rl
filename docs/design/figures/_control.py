# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "pyyaml"]
# ///
"""The linearized machine near upright, and the two classical controllers on it.

Shared by the figures in `pid-and-lqr.md`. Defines nothing that draws, so running this
file on its own does nothing.

The model is the one `scripts/scripted_swingup.py` linearizes for its own regulator:
four states, the pendulum's angle from upright and its rate, then the arm's angle and
its rate. The single input is rotor angular acceleration. Constants come from
`config/edukit.yaml` at import time.

The LQR weights and the solve are the project's own. The PID gains are not: the supplied
firmware's gains live in third-party source that is not committed here, so these were
tuned against this model for the illustration and are labelled as such wherever drawn.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from scipy.linalg import solve_continuous_are

ROOT = Path(__file__).resolve().parents[3]  # docs/design/figures -> repository root

INK = "#1a2733"
MUTED = "#5a6b7a"
BORDER = "#c9d2db"
PID_COLOUR = "#e8833a"
LQR_COLOUR = "#2e9e5b"
DANGER = "#d64545"
SENSOR = "#1f6feb"

# Tuned against the model below, not read from the firmware. See the module docstring.
# The inner pair places the pendulum loop at 6 rad/s with a damping ratio of 0.9, which
# is the fastest setting whose demand still fits inside the actuator's bound. Above it
# the loop saturates every cycle and rings instead of settling. The outer pair was swept
# for an arm recovery that settles without fighting the inner loop.
PID_INNER = dict(kp=143.0, ki=25.0, kd=17.1)
PID_OUTER = dict(kp=-0.02, kd=-0.04)
LEAN_LIMIT_RAD = 0.08
INTEGRAL_LIMIT = 0.2

CONTROL_DT_S = 1.0 / 500.0


def load() -> dict:
    """Constants, the linearized model, and the regulator the project solves for."""
    sys.path.insert(0, str(ROOT / "src"))
    from furuta.parameters import FurutaParameters

    p = FurutaParameters.from_yaml(ROOT / "config" / "edukit.yaml")
    omega_g_sq = p.omega_g_squared
    omega_g = math.sqrt(omega_g_sq)
    factor = 2.0 / 3.0 + p.normalized_shaft_inertia
    coupling = p.rotor_arm_length_m / (p.pendulum_length_m * factor)

    a = np.array(
        [
            [0.0, 1.0, 0.0, 0.0],
            [omega_g_sq, -omega_g / p.quality_factor, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
            [0.0, 0.0, 0.0, 0.0],
        ]
    )
    b = np.array([[0.0], [coupling], [0.0], [1.0]])
    weights = np.diag([100.0, 1.0, 1.0, 0.1])
    gains = (b.T @ solve_continuous_are(a, b, weights, [[1.0]])).ravel()

    return {
        "a": a,
        "b": b,
        "weights": weights,
        "gains": gains,
        "omega_g": omega_g,
        "coupling": coupling,
        "a_max": p.max_acceleration_rad_s2,
        "quality_factor": p.quality_factor,
    }


def lqr_controller(model: dict):
    """One gain vector across all four states."""
    gains = model["gains"]

    def step(state, memory, dt):
        return float(-gains @ state)

    return step


def pid_controller(model: dict):
    """Two nested loops, each reading one angle, unlike the firmware's summed pair.

    The outer loop watches the arm and asks the pendulum to lean. The inner loop drives
    the pendulum to that lean with proportional, integral and derivative terms, and its
    output is the rotor acceleration. `memory` also records the three inner terms so a
    figure can show what each contributed.
    """

    def step(state, memory, dt):
        tilt, _, arm, _ = state
        arm_error = -arm
        prior_arm = memory.get("arm_error")
        arm_rate = 0.0 if prior_arm is None else (arm_error - prior_arm) / dt
        memory["arm_error"] = arm_error
        lean = float(
            np.clip(
                PID_OUTER["kp"] * arm_error + PID_OUTER["kd"] * arm_rate,
                -LEAN_LIMIT_RAD,
                LEAN_LIMIT_RAD,
            )
        )

        error = lean - tilt
        memory["integral"] = float(
            np.clip(
                memory.get("integral", 0.0) + error * dt,
                -INTEGRAL_LIMIT,
                INTEGRAL_LIMIT,
            )
        )
        prior = memory.get("error")
        slope = 0.0 if prior is None else (error - prior) / dt
        memory["error"] = error

        terms = (
            PID_INNER["kp"] * error,
            PID_INNER["ki"] * memory["integral"],
            PID_INNER["kd"] * slope,
        )
        memory["terms"] = terms
        return float(sum(terms))

    return step


def simulate(model: dict, controller, seconds: float, start) -> dict:
    """Run one controller on the linearized model, clamped to the actuator's bound."""
    a, b, a_max = model["a"], model["b"].ravel(), model["a_max"]
    state = np.array(start, dtype=float)
    memory: dict = {}
    rows, terms = [], []
    for i in range(int(seconds / CONTROL_DT_S)):
        raw = controller(state, memory, CONTROL_DT_S)
        command = float(np.clip(raw, -a_max, a_max))
        rows.append((i * CONTROL_DT_S, *state, command, raw))
        terms.append(memory.get("terms", (0.0, 0.0, 0.0)))
        state = state + CONTROL_DT_S * (a @ state + b * command)
    rows = np.array(rows)
    return {
        "t": rows[:, 0],
        "tilt": rows[:, 1],
        "tilt_rate": rows[:, 2],
        "arm": rows[:, 3],
        "arm_rate": rows[:, 4],
        "command": rows[:, 5],
        "raw": rows[:, 6],
        "terms": np.array(terms),
    }


PLOT_STYLE = {
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
}


def titled(fig, title: str, subtitle: str) -> None:
    """The heading block the other design figures use."""
    fig.text(
        0.012,
        0.985,
        title,
        ha="left",
        va="top",
        fontsize=13.5,
        fontweight="bold",
        color=INK,
    )
    fig.text(
        0.012,
        0.918,
        subtitle,
        ha="left",
        va="top",
        fontsize=10.5,
        color=MUTED,
    )


def plain_axes(ax) -> None:
    """Drop the top and right spines and mute the rest."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(BORDER)
    ax.spines["left"].set_color(BORDER)

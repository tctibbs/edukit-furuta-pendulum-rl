# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Which scripted pump reaches the recoverable set at each acceleration bound, on paper.

This one draws nothing. It lives beside the figure scripts because `just figures 06`
runs it and because its output is read the same way they are, but its thirty-two rows
are a table the logbook reads in one paragraph, and the numbers that decide anything
are the environment's, in the logbook entries after it and the write-up's table. A chart
of them would be decoration over a result the logbook sets aside a few paragraphs on.

Experiment 05's planar sweep showed the bang-bang pump, `u = a_max * sign(rate *
cos(tilt))`, landing in the recoverable set at 11.78 rad/s^2 and overshooting it at
every bound above 25: each half swing then adds more energy than the window is wide.
Training runs at 60, so it needs a scripted controller that arrives there, both as
the existence proof the learner is measured against and as the sanity check on the
bound itself. Two candidates. The energy-regulated pump (Astrom and Furuta, Automatica
2000) is the sign law with its magnitude scaled by how far the energy still has to go,
so the push tapers as the separatrix nears. The kick pump is the firmware's own idea on
the acceleration path: at each pass through the bottom, one rest-to-rest pulse covering
a fixed arc against the swing, and nothing between pulses, so the arm never runs fast.

Every law runs on the reconciled planar model from rest near hanging, at each bound,
twice: with the manual's planar equations, and with the arm-rate term those drop. The
bang-bang and energy laws run behind the travel governor `scripts/scripted_swingup.py`
uses; the kick pump
has no governor, since its pulses alternate and the arm returns on its own. The catch
set scales with the bound, as it does in the environment. Writes
`planar_sizing.csv` into this experiment's `simulation/`.

    uv run docs/experiments/06-swing-up/figures/planar_sizing.py
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(EXPERIMENT.parents[2] / "src"))

from furuta.parameters import FurutaParameters  # noqa: E402
from furuta.planar import PlanarModel  # noqa: E402

UNSTABLE_POLE = 7.351
RECOVERABLE_WINDOW = 1.011
CONFIGURED_BOUND = 11.78
BOUNDS = (11.78, 25.0, 40.0, 60.0)
ALLOWANCE = 2.0
KICK_RAD = 0.393  # the firmware's 200-microstep kick
# (law, gain or arc): bang-bang, energy at two gains, and the kick pump.
LAWS = (("bang-bang", 0.0), ("energy", 4.0), ("energy", 8.0), ("kick", KICK_RAD))


def run(model: PlanarModel, a_max: float, law: str, gain: float, spin: bool, params):
    """One 40 s episode from rest near hanging, to the first entry into the set."""
    dt = params.control_dt_s
    v_max = params.max_rotor_rate_rad_s
    w2 = model.omega_g_squared
    theta, theta_dot, phi, phi_dot = math.pi - 0.05, 0.0, 0.0, 0.0
    t = 0.0
    peak_arm = peak_arm_rate = 0.0
    kicks = 0
    # Kick pump state: the pulse is `half` steps at +a then `half` at -a.
    half = max(1, round(math.sqrt(gain / a_max) / dt)) if law == "kick" else 0
    pulse_step, pulse_dir, prev_from_hanging = None, 0.0, None
    step = 0
    while t < 40.0:
        tilt = (theta + math.pi) % (2 * math.pi) - math.pi
        if law == "kick":
            from_hanging = tilt - math.copysign(math.pi, tilt) if tilt != 0 else 0.0
            in_pulse = pulse_step is not None and step - pulse_step < 2 * half
            if (
                not in_pulse
                and prev_from_hanging is not None
                and prev_from_hanging * from_hanging < 0
            ):
                # Through the bottom: push against the swing, as the sign law does
                # there, for one rest-to-rest pulse.
                pulse_dir = -math.copysign(1.0, theta_dot) if theta_dot else 1.0
                pulse_step = step
                kicks += 1
                in_pulse = True
            prev_from_hanging = from_hanging
            if in_pulse:
                u = pulse_dir * a_max
                if step - pulse_step >= half:
                    u = -u
            else:
                u = 0.0
        else:
            direction = 1.0 if theta_dot * math.cos(theta) >= 0 else -1.0
            magnitude = 1.0
            if law == "energy":
                fraction = 1.0 + (0.5 * theta_dot**2 + w2 * (math.cos(theta) - 1.0)) / (
                    2 * w2
                )
                magnitude = min(1.0, max(0.0, gain * (1.0 - fraction)))
            u = a_max * magnitude * direction
            stop = phi_dot**2 / (2 * a_max)
            if phi_dot > 0 and phi + stop >= 0.95 * ALLOWANCE:
                u = -a_max
            elif phi_dot < 0 and phi - stop <= -0.95 * ALLOWANCE:
                u = a_max
        theta, theta_dot = model.step(
            theta, theta_dot, u, dt, rotor_rate=phi_dot if spin else 0.0
        )
        v = max(-v_max, min(v_max, phi_dot + u * dt))
        phi += 0.5 * (phi_dot + v) * dt
        phi_dot = v
        t += dt
        step += 1
        peak_arm = max(peak_arm, abs(phi))
        peak_arm_rate = max(peak_arm_rate, abs(phi_dot))
        tilt = (theta + math.pi) % (2 * math.pi) - math.pi
        mode = theta_dot + UNSTABLE_POLE * tilt
        if (
            abs(tilt) < 0.35
            and abs(mode) < RECOVERABLE_WINDOW * a_max / CONFIGURED_BOUND
        ):
            return {
                "arrives": 1,
                "arrive_s": round(t, 2),
                "mode_rad_s": round(mode, 3),
                "kicks": kicks if law == "kick" else "",
                "peak_arm_rad": round(peak_arm, 2),
                "peak_arm_rate_rad_s": round(peak_arm_rate, 2),
            }
    return {
        "arrives": 0,
        "arrive_s": "",
        "mode_rad_s": "",
        "kicks": kicks if law == "kick" else "",
        "peak_arm_rad": round(peak_arm, 2),
        "peak_arm_rate_rad_s": round(peak_arm_rate, 2),
    }


def main() -> int:
    """Sweep bound, law and the arm-rate term; write the rows and print them."""
    params = FurutaParameters.from_yaml()
    model = PlanarModel.from_parameters(params)
    rows = []
    for a_max in BOUNDS:
        for law, gain in LAWS:
            for spin in (False, True):
                rows.append(
                    {
                        "accel_bound_rad_s2": a_max,
                        "pump": law,
                        "gain_or_arc": gain,
                        "arm_rate_term": int(spin),
                        **run(model, a_max, law, gain, spin, params),
                    }
                )
    out = EXPERIMENT / "simulation/planar_sizing.csv"
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print("  ".join(f"{k}={v}" for k, v in row.items()))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

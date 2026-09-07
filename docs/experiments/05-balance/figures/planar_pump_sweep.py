# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""The governed pump on the reconciled planar model, across acceleration bounds.

The full environment's pump plateaus at the configured 11.78 rad/s^2. This asks the
planar model the same question, with the same pump law, governor and handover rule as
`scripts/scripted_swingup.py`, at the configured bound and above it, and once more
with the quadratic drag removed. It writes `planar_pump.csv` beside the experiment and
prints the table. The planar equation carries no rotor-rate terms, so its answer is a
check on the plant's losses rather than a second opinion on PhysX.

    uv run docs/experiments/05-balance/figures/planar_pump_sweep.py
"""

from __future__ import annotations

import csv
import math
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(EXPERIMENT.parents[2] / "src"))

from furuta.parameters import FurutaParameters  # noqa: E402
from furuta.planar import PlanarModel  # noqa: E402

UNSTABLE_POLE = 7.351
RECOVERABLE_WINDOW = 1.011
CONFIGURED_BOUND = 11.78
BOUNDS = (11.78, 15.0, 20.0, 25.0, 30.0, 40.0, 188.5)
ALLOWANCE = 2.0


def run(model: PlanarModel, a_max: float, params: FurutaParameters) -> dict:
    """One 40 s episode from rest near hanging, under the script's three rules."""
    dt = params.control_dt_s
    v_max = params.max_rotor_rate_rad_s
    theta, theta_dot, phi, phi_dot = math.pi - 0.05, 0.0, 0.0, 0.0
    t = 0.0
    reversals = 0
    sign = 0.0
    turn_angle = -0.05
    peak = 0.0
    while t < 40.0:
        u = a_max if theta_dot * math.cos(theta) >= 0 else -a_max
        stop = phi_dot**2 / (2 * a_max)
        if phi_dot > 0 and phi + stop >= 0.95 * ALLOWANCE:
            u = -a_max
        elif phi_dot < 0 and phi - stop <= -0.95 * ALLOWANCE:
            u = a_max
        theta, theta_dot = model.step(theta, theta_dot, u, dt)
        v = max(-v_max, min(v_max, phi_dot + u * dt))
        phi += 0.5 * (phi_dot + v) * dt
        phi_dot = v
        t += dt
        tilt = (theta + math.pi) % (2 * math.pi) - math.pi
        from_hanging = tilt - math.copysign(math.pi, tilt) if tilt != 0 else 0.0
        peak = max(peak, math.pi - abs(tilt))
        sign_now = math.copysign(1.0, theta_dot) if theta_dot != 0 else sign
        if (
            sign * sign_now < 0
            and math.pi - abs(tilt) > 0.1
            and abs(from_hanging - turn_angle) > 0.1
        ):
            reversals += 1
            turn_angle = from_hanging
        sign = sign_now
        mode = theta_dot + UNSTABLE_POLE * tilt
        if (
            abs(tilt) < 0.35
            and abs(mode) < RECOVERABLE_WINDOW * a_max / CONFIGURED_BOUND
        ):
            return {
                "arrives": 1,
                "arrive_s": round(t, 2),
                "reversals": reversals,
                "mode_rad_s": round(mode, 3),
                "peak_from_hanging_deg": round(math.degrees(peak), 1),
            }
    return {
        "arrives": 0,
        "arrive_s": "",
        "reversals": reversals,
        "mode_rad_s": "",
        "peak_from_hanging_deg": round(math.degrees(peak), 1),
    }


def main() -> int:
    """Sweep the bound, then drop the drag term, and write the rows."""
    params = FurutaParameters.from_yaml()
    model = PlanarModel.from_parameters(params)
    rows = []
    for a_max in BOUNDS:
        rows.append(
            {
                "plant": "reconciled",
                "accel_bound_rad_s2": a_max,
                **run(model, a_max, params),
            }
        )
    no_drag = replace(model, drag_coeff=0.0)
    rows.append(
        {
            "plant": "no drag",
            "accel_bound_rad_s2": CONFIGURED_BOUND,
            **run(no_drag, CONFIGURED_BOUND, params),
        }
    )
    out = EXPERIMENT / "planar_pump.csv"
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

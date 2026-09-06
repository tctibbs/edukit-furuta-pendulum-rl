"""Run the dissipation ladder inside PhysX and write effective Q against amplitude.

Each rung releases the pendulum with the rotor held and reads the effective quality
factor of the decay through `furuta.pump.qeff_vs_amplitude`, the same function the
hardware capture and the planar ladder are read through. The equation half of the
comparison is in `docs/experiments/04-model-reconciliation/writeup.md`.

The 4 kHz default does not rest on this ladder. Running both rates here was meant to
expose a solver loss at the production 1 kHz and did not. The rate separates on the
driven trace replay, where 1 kHz leaves the pendulum 114.8 degrees from upright against
91.7 at 4 kHz.

Run on the training host:

    python -u scripts/diag_dissipation.py --headless --plant after \
        --out results/qeff_after.csv
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from isaaclab.app import AppLauncher

from furuta.shutdown import close_and_exit

# Same releases as the equation's ladder, for a curve that compares rung for rung.
LADDER_DEG = (162.0, 135.0, 108.0, 82.0, 58.0, 38.0, 22.0)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--plant",
    choices=["before", "after"],
    default="after",
    help="before zeroes Coulomb, drag and tilt; after uses the reconciled config",
)
parser.add_argument("--seconds", type=float, default=32.0, help="decay length per rung")
parser.add_argument(
    "--physics-hz",
    type=float,
    default=4000.0,
    help="physics rate; the ladder reads within 0.01 in Q at the production 1000",
)
parser.add_argument("--out", required=True)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Ring down every rung and write amplitude against effective Q."""
    import gymnasium as gym
    import torch

    import furuta.tasks  # noqa: F401 (registration side effect)
    from furuta.env import PARAMS, FurutaEnvCfg
    from furuta.freeswing import Trace
    from furuta.parameters import gravity_for_tilt
    from furuta.pump import RingdownSegment, qeff_vs_amplitude

    cfg = FurutaEnvCfg()
    cfg.scene.num_envs = len(LADDER_DEG)
    cfg.scene.env_spacing = 1.2

    if args.plant == "before":
        cfg.pivot_coulomb_deg_per_half_swing = 0.0
        cfg.pivot_drag_coeff = 0.0
        cfg.sim.gravity = gravity_for_tilt(0.0, PARAMS.gravity_m_s2)

    cfg.sim.dt = 1.0 / args.physics_hz
    cfg.decimation = max(1, round(PARAMS.control_dt_s * args.physics_hz))

    # The balance guards do not apply to a ring-down. The pendulum spends the whole run
    # far from upright, and that is the fall-over termination. The episode also has to
    # outlast the longest decay.
    cfg.episode_length_s = args.seconds * 4.0
    cfg.max_pendulum_angle_rad = math.pi
    cfg.max_rotor_angle_rad = 1.0e6
    cfg.reset_upright = False
    cfg.initial_pendulum_angle_range = [0.0, 0.0]
    cfg.initial_pendulum_rate_range = [0.0, 0.0]
    cfg.initial_rotor_angle_range = [0.0, 0.0]
    cfg.initial_rotor_rate_range = [0.0, 0.0]
    cfg.hanging_reset_fraction = 0.0
    cfg.balance_reset_fraction = 0.0

    print(
        f"[cfg  ] plant={args.plant} physics={args.physics_hz:.0f} Hz "
        f"decimation={cfg.decimation} "
        f"gravity={tuple(round(g, 4) for g in cfg.sim.gravity)}",
        flush=True,
    )

    env = gym.make("Furuta-Balance-Direct-v0", cfg=cfg).unwrapped
    env.reset()
    print(
        f"[cfg  ] coulomb={env._dissipation.coulomb_rad_s2:.4f} rad/s^2 "
        f"drag={env._dissipation.drag_coeff:.4f} /rad active={env._dissipation.active}",
        flush=True,
    )

    # The asset's zero is the hanging pose. A ladder amplitude therefore sets the joint
    # directly, and one environment per rung releases the ladder from rest at once.
    joint_pos = env.robot.data.default_joint_pos.clone()
    joint_vel = torch.zeros_like(joint_pos)
    for i, amplitude in enumerate(LADDER_DEG):
        joint_pos[i, env._pendulum_idx[0]] = math.radians(amplitude)
        joint_pos[i, env._rotor_idx[0]] = 0.0
    env.robot.write_joint_state_to_sim(joint_pos, joint_vel)
    env._actuator.reset()

    steps = int(args.seconds / env.step_dt)
    zero = torch.zeros(cfg.scene.num_envs, 1, device=env.device)
    times: list[float] = []
    angles: list[list[float]] = []
    for step in range(steps):
        env.step(zero)
        times.append(step * env.step_dt)
        angles.append(env.robot.data.joint_pos[:, env._pendulum_idx[0]].cpu().tolist())
        if step % 2000 == 0:
            print(f"[run  ] step {step}/{steps}", flush=True)

    rows = []
    for i, amplitude in enumerate(LADDER_DEG):
        series = tuple(math.degrees(row[i]) for row in angles)
        segment = RingdownSegment(amplitude, Trace(tuple(times), series))
        pairs = qeff_vs_amplitude(segment)
        print(f"[rung ] {amplitude:6.1f} deg -> {len(pairs)} points", flush=True)
        for measured, quality in pairs:
            rows.append(
                {
                    "release_deg": amplitude,
                    "amplitude_deg": round(measured, 4),
                    "quality": round(quality, 4),
                }
            )

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["release_deg", "amplitude_deg", "quality"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"[done ] wrote {len(rows)} rows to {path}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    code = main()
    close_and_exit(simulation_app, code)

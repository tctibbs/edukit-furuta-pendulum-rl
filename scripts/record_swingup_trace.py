"""Dump one swing-up episode to CSV, one row per control step.

The pumping is the part of this task worth looking at, and a success rate cannot show
it. Each row carries the tilt from vertical, the rotor angle, and the commanded
acceleration, which together show the policy driving the rotor in phase with the swing
and then switching to holding once the pendulum arrives.

The trace is a single episode from one environment. A mean over the evaluator's 256
episodes would average the strokes away. `--env` picks which of the batch to record.

Run on the training host:

    python scripts/record_swingup_trace.py --headless \
        --physics-hz 4000 --accel-bound 60 \
        --checkpoint logs/rsl_rl/furuta_swingup/r7-smooth/model_599.pt \
        --out traces/swingup.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import traceback
from pathlib import Path

from isaaclab.app import AppLauncher

from furuta.shutdown import close_and_exit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--stepped-rotor",
    action="store_true",
    help="hand the drive one target per control period, the plant every run before"
    " ADR-0006 trained on, instead of walking it across the substeps",
)
parser.add_argument("--task", default="Furuta-SwingUp-Direct-Play-v0")
parser.add_argument("--checkpoint", required=True)
parser.add_argument("--num-envs", type=int, default=16)
parser.add_argument("--env", type=int, default=0, help="which environment to record")
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--out", required=True)
parser.add_argument(
    "--max-rotor-rad",
    type=float,
    default=None,
    help="override the travel termination, matching a run trained with one",
)
parser.add_argument(
    "--no-squash",
    action="store_true",
    help="bypass the tanh bound, for checkpoints trained before it existed",
)
parser.add_argument(
    "--velocity-iters",
    type=int,
    default=None,
    help="raise the PhysX velocity iteration floor",
)
parser.add_argument(
    "--physics-hz",
    type=float,
    default=None,
    help="override the physics rate; the control rate stays at 500 Hz",
)
parser.add_argument(
    "--accel-bound",
    type=float,
    default=None,
    help="rotor acceleration bound and action scale, rad/s^2, in place of the "
    "configured 11.78. Must match the bound the checkpoint trained with: the "
    "checkpoint does not record it, and a wrong value rescales every command "
    "without failing. See ADR-0004",
)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Roll one episode out and write its per-step trace."""
    import gymnasium as gym
    import torch
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from rsl_rl.runners import OnPolicyRunner

    import furuta.tasks  # noqa: F401 (registration side effect)
    from furuta.env import wrap_to_pi

    spec = gym.spec(args.task)
    # Instances, as the evaluator makes them. Configuring the class itself mutates
    # the shared defaults every later `gym.make` in the process would inherit.
    cfg = spec.kwargs["env_cfg_entry_point"]()
    cfg.rotor_target_interpolation = not args.stepped_rotor
    agent_cfg = spec.kwargs["rsl_rl_cfg_entry_point"]()
    cfg.scene.num_envs = args.num_envs
    cfg.seed = args.seed
    if args.max_rotor_rad is not None:
        cfg.max_rotor_angle_rad = args.max_rotor_rad
        print(f"[cfg  ] max_rotor_angle_rad={args.max_rotor_rad}", flush=True)
    if args.no_squash:
        cfg.squash_actions = False
        print("[cfg  ] squash_actions=False", flush=True)
    if args.velocity_iters is not None:
        cfg.sim.physx.min_velocity_iteration_count = args.velocity_iters
        cfg.sim.physx.enable_external_forces_every_iteration = True
        print(f"[cfg  ] min_velocity_iteration_count={args.velocity_iters}", flush=True)
    if args.physics_hz is not None:
        cfg.sim.dt = 1.0 / args.physics_hz
        cfg.decimation = max(1, round(0.002 * args.physics_hz))
        print(f"[cfg  ] sim.dt={cfg.sim.dt} decimation={cfg.decimation}", flush=True)
    if args.accel_bound is not None:
        cfg.max_acceleration_rad_s2 = args.accel_bound
        print(f"[cfg  ] max_acceleration_rad_s2={args.accel_bound}", flush=True)

    env = gym.make(args.task, cfg=cfg)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)
    runner = OnPolicyRunner(
        env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device
    )
    runner.load(args.checkpoint)
    policy = runner.get_inference_policy(device=agent_cfg.device)

    inner = env.unwrapped
    i = args.env
    steps = int(cfg.episode_length_s / inner.step_dt)
    rows = []

    obs = env.get_observations()
    for step in range(steps):
        with torch.inference_mode():
            actions = policy(obs)
        obs, _, _, _ = env.step(actions)

        pendulum, rotor = inner._quantized_angles()
        tilt = wrap_to_pi(pendulum - math.pi)
        rows.append(
            {
                "t_s": round(step * inner.step_dt, 4),
                "tilt_deg": round(math.degrees(tilt[i].item()), 4),
                "pendulum_rate_rad_s": round(inner._pendulum_vel[i].item(), 4),
                "rotor_rad": round(rotor[i].item(), 5),
                "rotor_rate_rad_s": round(inner._actuator.velocity[i].item(), 4),
                "action": round(inner._action[i].item(), 5),
            }
        )

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[done ] wrote {len(rows)} rows to {path}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    # An exception here has to become a non-zero exit. Left to propagate, Kit's own
    # teardown returns 0 after the traceback, and a driver that trusts the code then
    # runs every later step against a checkpoint that was never written.
    try:
        code = main() or 0
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        code = 1
    close_and_exit(simulation_app, code)

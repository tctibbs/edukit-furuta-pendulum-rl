"""Score a swing-up checkpoint from hanging rest.

Success is one number with two halves, because either alone can be passed by a policy
that has not done the task. A pendulum that reaches vertical and coasts through it has
not swung up, and a policy scored only on where it ends could have spent the episode
hanging and been flicked upright by the last stroke.

An episode succeeds when the pendulum is inside `--hold-deg` of vertical for the whole
of the last `--hold-s` seconds. The swing-up time is separately reported as the first
step at which the tilt goes inside that window. Episodes terminated on the rotor travel
bound are failures, never dropped samples.

Every episode starts hanging with the spread `FurutaSwingUpPlayEnvCfg` sets, so a seed
is a draw of 256 initial conditions. Run several and report the spread across them.

Run on the training host:

    python scripts/evaluate_swingup.py --headless \
        --physics-hz 4000 --accel-bound 60 \
        --checkpoint logs/rsl_rl/furuta_swingup/r7-smooth/model_599.pt
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
parser.add_argument("--num-envs", type=int, default=256)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--hold-deg", type=float, default=3.0)
parser.add_argument(
    "--hold-s", type=float, default=5.0, help="trailing window that must stay inside"
)
parser.add_argument("--out", default=None, help="csv path for the per-seed row")
parser.add_argument(
    "--max-rotor-rad",
    type=float,
    default=None,
    help="override the travel termination to match a run trained with one",
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
    "--accel-bound",
    type=float,
    default=None,
    help="rotor acceleration bound and action scale, rad/s^2, in place of the "
    "configured 11.78. Must match the bound the checkpoint trained with: the "
    "checkpoint does not record it, and a wrong value rescales every command "
    "without failing. See ADR-0004",
)
parser.add_argument(
    "--physics-hz",
    type=float,
    default=None,
    help="simulation rate. The swing-up checkpoints trained at 4000. Experiment 04's "
    "replay of a logged hardware swing-up rose 23 degrees higher at 4 kHz than at "
    "1 kHz on the stepped target; 1 kHz on the walked target is untested (ADR-0006)",
)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Roll one seed's worth of episodes out and write a single summary row."""
    import gymnasium as gym
    import torch
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from rsl_rl.runners import OnPolicyRunner

    import furuta.tasks  # noqa: F401  (registration side effect)
    from furuta.env import wrap_to_pi

    spec = gym.spec(args.task)
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
    if args.accel_bound is not None:
        cfg.max_acceleration_rad_s2 = args.accel_bound
        print(f"[cfg  ] max_acceleration_rad_s2={args.accel_bound}", flush=True)
    if args.physics_hz is not None:
        cfg.sim.dt = 1.0 / args.physics_hz
        cfg.decimation = max(1, round(0.002 * args.physics_hz))
        print(
            f"[cfg  ] physics_hz={args.physics_hz} decimation={cfg.decimation}",
            flush=True,
        )

    # The scored window is the configured episode, and the time-out has to fall outside
    # it: it fires one step before the episode length and resets every environment to
    # hanging. A loop running exactly the episode length reads a hanging pendulum on its
    # last iteration and scores every survivor as leaving the hold window.
    duration = cfg.episode_length_s
    cfg.episode_length_s = duration + 1.0

    env = gym.make(args.task, cfg=cfg)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)
    runner = OnPolicyRunner(
        env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device
    )
    runner.load(args.checkpoint)
    policy = runner.get_inference_policy(device=agent_cfg.device)

    inner = env.unwrapped
    device = inner.device
    n = args.num_envs
    steps = int(duration / inner.step_dt)
    hold_steps = int(args.hold_s / inner.step_dt)
    tol = math.radians(args.hold_deg)

    # Per environment, carried across the whole episode. Isaac Lab resets an
    # environment the moment it terminates and it then runs a fresh episode inside the
    # same loop. Every statistic below is frozen at an environment's first termination.
    # Without that freeze an environment that terminates at step 50 keeps contributing
    # arrivals and hold samples from episodes that are not the one being scored.
    arrived = torch.full((n,), -1, dtype=torch.long, device=device)  # first step inside
    left_late = torch.zeros(n, dtype=torch.bool, device=device)  # outside during hold
    terminated = torch.zeros(n, dtype=torch.bool, device=device)
    term_step = torch.full((n,), -1, dtype=torch.long, device=device)
    peak_rotor = torch.zeros(n, device=device)
    # The arm's speed, from the actuator's own integrator. A pump at a raised bound
    # can ask for rotor speeds the bench has never demonstrated.
    peak_rotor_rate = torch.zeros(n, device=device)

    obs = env.get_observations()
    for step in range(steps):
        with torch.inference_mode():
            actions = policy(obs)
        obs, _, _, _ = env.step(actions)

        pendulum, rotor = inner._quantized_angles()
        tilt = torch.abs(wrap_to_pi(pendulum - math.pi))
        inside = tilt <= tol
        live = ~terminated

        first = inside & (arrived < 0) & live
        arrived = torch.where(first, torch.full_like(arrived, step), arrived)
        if step >= steps - hold_steps:
            left_late |= ~inside & live
        peak_rotor = torch.maximum(peak_rotor, torch.abs(rotor) * live)
        peak_rotor_rate = torch.maximum(
            peak_rotor_rate, torch.abs(inner._actuator.velocity) * live
        )

        # `reset_terminated` is the travel bound alone. `dones` also unions the episode
        # time-out. Scoring against `dones` marks every completed episode a failure.
        now = inner.reset_terminated.bool() & live
        term_step = torch.where(now, torch.full_like(term_step, step), term_step)
        terminated |= now

    # An environment that never entered the hold window has not held it either.
    success = (~left_late) & (~terminated) & (arrived >= 0)
    reached = arrived >= 0
    swing_s = torch.where(reached, arrived.float() * inner.step_dt, torch.nan)

    # Provenance first. Four of the five evaluation defects found so far were found by
    # reading configuration; a row that carries none cannot be read that way later.
    row = {
        "task": args.task,
        "checkpoint": args.checkpoint,
        "physics_hz": round(1.0 / cfg.sim.dt),
        "accel_bound_rad_s2": inner._actuator.max_acceleration,
        "max_rotor_angle_rad": round(cfg.max_rotor_angle_rad, 4),
        "seed": args.seed,
        "episodes": n,
        "success_rate": success.float().mean().item(),
        "reached_vertical_rate": reached.float().mean().item(),
        "terminated_rate": terminated.float().mean().item(),
        "swingup_s_median": torch.nanmedian(swing_s).item(),
        "swingup_s_p90": torch.nanquantile(swing_s[reached], 0.9).item()
        if reached.any()
        else float("nan"),
        "peak_rotor_rad_max": peak_rotor.max().item(),
        "peak_rotor_rate_rad_s_max": peak_rotor_rate.max().item(),
        "term_s_median": (term_step[terminated].float() * inner.step_dt).median().item()
        if terminated.any()
        else float("nan"),
    }
    print(f"[eval ] {row}", flush=True)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        if not new:
            with path.open(newline="") as handle:
                header = next(csv.reader(handle), [])
            if header != list(row):
                raise SystemExit(
                    f"{path} has columns {header}, this run writes {list(row)}; "
                    "move the old file aside rather than mixing the two"
                )
        with path.open("a", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            if new:
                writer.writeheader()
            writer.writerow(row)
        print(f"[done ] appended to {path}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    # An exception here has to become a non-zero exit. Left to propagate, Kit's own
    # teardown returns 0 after the traceback, and a driver that trusts the code then
    # runs every later step against a row that was never written.
    try:
        code = main() or 0
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        code = 1
    close_and_exit(simulation_app, code)

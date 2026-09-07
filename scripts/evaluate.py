"""Score a balance checkpoint against the Milestone 05 gate.

Two measurements, both over 30 second episodes in the Play variant.

**Hold.** The fraction of episodes that stay within 3 degrees of vertical for the whole
episode. The 3 degrees is the window at which the stock firmware engages its balance
controller (Manual Sec. 1), reused here as a hold tolerance, which the manual does not
do. A terminated episode is a failure, never a dropped sample.

**Disturbance recovery.** One impulse per episode, added to pendulum angular velocity at
a step drawn from the middle of the episode. The magnitude grid runs to 1.011 rad/s
because that is the entire recoverable window at upright, from
`omega_r^2 * a_max / omega_g`, so the sweep spans nothing to everything by construction.
Recovery means back inside 3 degrees within 1 second and still inside at the end.

Rotor travel is recorded alongside, because a recovery that costs most of the pi/2
travel bound does not survive on a unit whose encoder is cabled to the arm.

Run on the training host:

    python scripts/evaluate.py --headless \
        --checkpoint logs/rsl_rl/furuta_balance/seed1/model_299.pt
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from isaaclab.app import AppLauncher

from furuta.shutdown import close_and_exit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--task", default="Furuta-Balance-Direct-Play-v0")
parser.add_argument("--checkpoint", required=True)
parser.add_argument("--num-envs", type=int, default=256)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument(
    "--accel-bound",
    type=float,
    default=None,
    help="the bound the checkpoint trained with, when it is not the configured one",
)
parser.add_argument("--hold-deg", type=float, default=3.0)
parser.add_argument(
    "--settle-s",
    type=float,
    default=0.0,
    help="score the hold only after this many seconds; 0 scores the whole episode, "
    "which is right for a start inside the envelope and wrong for one outside it",
)
parser.add_argument("--recover-window-s", type=float, default=1.0)
parser.add_argument("--out", default=None, help="csv path for the per-magnitude rows")
parser.add_argument(
    "--kicks",
    default="0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0",
    help="disturbance magnitudes in rad/s; 0 is the undisturbed hold measurement",
)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Run the hold and disturbance sweeps, writing one row per magnitude."""
    import gymnasium as gym
    import torch
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from rsl_rl.runners import OnPolicyRunner

    import furuta.tasks  # noqa: F401  (registration side effect)

    spec = gym.spec(args.task)
    env_cfg = spec.kwargs["env_cfg_entry_point"]()
    agent_cfg = spec.kwargs["rsl_rl_cfg_entry_point"]()
    env_cfg.scene.num_envs = args.num_envs
    agent_cfg.seed = args.seed
    if args.accel_bound is not None:
        from furuta.parameters import FurutaParameters

        configured = FurutaParameters.from_yaml().max_acceleration_rad_s2
        env_cfg.max_acceleration_rad_s2 = args.accel_bound
        if getattr(env_cfg, "reset_in_recoverable_set", False):
            scale = args.accel_bound / configured
            env_cfg.reset_mode_range = [v * scale for v in env_cfg.reset_mode_range]
        print(f"[cfg  ] max_acceleration_rad_s2={args.accel_bound}")

    print(
        f"[stack] torch {torch.__version__} cuda_available={torch.cuda.is_available()}"
    )

    # The scored window is the configured episode. The time-out fires one step before
    # it and resets every environment in place, so the loop below must stop before
    # that reset or its last iteration reads a freshly reset pendulum.
    scored_s = env_cfg.episode_length_s
    env_cfg.episode_length_s = scored_s + 1.0
    env = gym.make(args.task, cfg=env_cfg, render_mode=None)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner = OnPolicyRunner(
        env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device
    )
    runner.load(args.checkpoint)
    policy = runner.get_inference_policy(device=agent_cfg.device)
    print(f"[ckpt ] {args.checkpoint}")

    unwrapped = env.unwrapped
    device = unwrapped.device
    horizon = int(scored_s / unwrapped.step_dt)
    hold_rad = math.radians(args.hold_deg)
    recover_steps = int(args.recover_window_s / unwrapped.step_dt)
    settle_steps = int(args.settle_s / unwrapped.step_dt)
    pendulum_idx = unwrapped._pendulum_idx[0]

    rows = []
    for kick in [float(k) for k in args.kicks.split(",")]:
        torch.manual_seed(args.seed)
        unwrapped.reset()
        obs = env.get_observations()

        n = unwrapped.num_envs
        # One kick per episode, in the middle so there is settling time either side.
        kick_at = torch.randint(
            int(0.17 * horizon), int(0.83 * horizon), (n,), device=device
        )
        sign = torch.where(torch.rand(n, device=device) < 0.5, -1.0, 1.0)

        held = torch.ones(n, dtype=torch.bool, device=device)
        recovered = torch.ones(n, dtype=torch.bool, device=device)
        terminated = torch.zeros(n, dtype=torch.bool, device=device)
        peak = torch.zeros(n, device=device)
        travel = torch.zeros(n, device=device)
        kicked_step = torch.full((n,), -1, dtype=torch.long, device=device)

        for step in range(horizon):
            with torch.inference_mode():
                actions = policy(obs)
            obs, _, _, _ = env.step(actions)

            # An episode that falls over or runs out of rotor travel is reset by the
            # environment, which puts the pendulum back near upright. Without recording
            # it here, the very next step reads as inside the envelope and the episode
            # scores as a recovery. Termination is a failure of both measures.
            #
            # `reset_terminated` and not the wrapper's `dones`: `dones` is the union of
            # termination and time-out, and every episode that survives its full 30
            # seconds times out by construction, so scoring on `dones` marks a perfect
            # run as a failure.
            ended = unwrapped.reset_terminated.bool()
            terminated |= ended
            held &= ~ended

            if kick > 0.0:
                due = kick_at == step
                if due.any():
                    vel = unwrapped.robot.data.joint_vel.clone()
                    vel[due, pendulum_idx] += kick * sign[due]
                    unwrapped.robot.write_joint_state_to_sim(
                        unwrapped.robot.data.joint_pos, vel
                    )
                    kicked_step[due] = step

            angle = unwrapped.robot.data.joint_pos[:, pendulum_idx]
            upright = torch.atan2(
                torch.sin(angle - math.pi), torch.cos(angle - math.pi)
            )
            outside = upright.abs() > hold_rad

            # Hold is scored from the end of the settle window to the end of the
            # episode, so any excursion in that span fails it. With no settle window
            # that is the whole episode.
            if step >= settle_steps:
                held &= ~outside
            peak = torch.maximum(peak, upright.abs())
            travel = torch.maximum(travel, unwrapped._actuator.position.abs())

            # Recovery only looks after the kick's grace window.
            if kick > 0.0:
                late = (kicked_step >= 0) & (step > kicked_step + recover_steps)
                recovered &= ~(late & outside)
        recovered &= ~terminated

        row = {
            "kick_rad_s": kick,
            "episodes": n,
            "hold_rate": held.float().mean().item(),
            "recovery_rate": recovered.float().mean().item()
            if kick > 0
            else float("nan"),
            "terminated_rate": terminated.float().mean().item(),
            "peak_excursion_deg": math.degrees(peak.mean().item()),
            "max_rotor_travel_rad": travel.max().item(),
        }
        rows.append(row)
        print(
            f"[eval ] kick {kick:4.2f} rad/s  hold {row['hold_rate']:.3f}"
            f"  recover {row['recovery_rate']:.3f}"
            f"  term {row['terminated_rate']:.3f}"
            f"  peak {row['peak_excursion_deg']:5.2f} deg"
            f"  rotor {row['max_rotor_travel_rad']:5.2f} rad"
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"[out  ] {out}")

    env.close()
    return 0


if __name__ == "__main__":
    main()
    close_and_exit(simulation_app)

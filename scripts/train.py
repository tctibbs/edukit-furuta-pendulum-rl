"""Train a balance policy with rsl_rl's PPO.

Isaac Lab ships a training script, and it cannot run this task. It imports
`isaaclab_tasks`, which registers the built-in environments and nothing else, so
`Furuta-Balance-Direct-v0` does not exist by the time it resolves `--task`. This wrapper
is the stock flow with `furuta.tasks` imported, which is what registers the id.

Run on the training host:

    python scripts/train.py --headless --num-envs 4096 --seed 1

Read the log, not the exit code. This stack has returned 0 while blocked on a EULA
prompt, while looping forever, and while dying of a native access violation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from isaaclab.app import AppLauncher

from furuta.shutdown import close_and_exit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--task", default="Furuta-Balance-Direct-v0")
parser.add_argument("--num-envs", type=int, default=1024)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--max-iterations", type=int, default=None)
parser.add_argument("--velocity-window", type=int, default=None)
parser.add_argument(
    "--rotor-travel-deadband",
    type=float,
    default=None,
    help="override the travel reward deadband, so a wider bound is usable",
)
parser.add_argument(
    "--max-rotor-rad",
    type=float,
    default=None,
    help="override the rotor travel bound, for testing what that bound costs",
)
parser.add_argument(
    "--governor-weight",
    type=float,
    default=None,
    help="weight on the squared projected travel overrun, negative to charge",
)
parser.add_argument(
    "--governor-margin",
    type=float,
    default=None,
    help="stopping-point allowance in rad the governor term prices past",
)
parser.add_argument(
    "--physics-hz",
    type=float,
    default=None,
    help="override the physics rate; the control rate stays at 500 Hz",
)
parser.add_argument(
    "--upright-reward",
    choices=["quadratic", "cosine"],
    default=None,
    help="shape of the upright term; cosine is the one experiment 05 showed too flat",
)
parser.add_argument(
    "--init-noise-std",
    type=float,
    default=None,
    help="initial policy noise; 0.3 is the value experiment 05 showed learns worse",
)
parser.add_argument(
    "--entropy-coef",
    type=float,
    default=None,
    help="override PPO's entropy bonus; zero stops paying for action-std inflation",
)
parser.add_argument(
    "--pump-power",
    type=float,
    default=None,
    help="weight on instantaneous energy input; dense gradient on pump phase",
)
parser.add_argument(
    "--rotor-rate-range",
    type=float,
    default=None,
    help="reset spread for the rotor rate in rad/s; crossing states need a live arm",
)
parser.add_argument(
    "--swing-rate",
    type=float,
    default=None,
    help="ungated pendulum-rate cost, negative to charge; prices a sustained swing",
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
    "configured 11.78. A hypothesis run under ADR-0004: the balance path's physical "
    "bound is unmeasured. Scales the momentum task's reset mode range with it",
)
parser.add_argument(
    "--action-rate-weight",
    type=float,
    default=None,
    help="reward weight on how much the command changes between steps, per squared "
    "normalised unit. Negative. At the default of -0.01 the chatter this prices costs "
    "7e-6 per step against an alive term of 1.0, which is no price at all",
)
parser.add_argument(
    "--rotor-rate-weight",
    type=float,
    default=None,
    help="reward weight on the arm's speed, per (rad/s)^2 per step. Negative. Prices "
    "the arm swinging back and forth, which the travel term prices only at its ends",
)
parser.add_argument(
    "--travel-weight",
    type=float,
    default=None,
    help="reward weight on rotor travel past the deadband, per radian per step. "
    "Negative. Not terminating on travel and not charging for it are different "
    "things: with no charge the policy uses the whole arm",
)
parser.add_argument("--run-name", default=None)
parser.add_argument(
    "--init-from",
    default=None,
    help="checkpoint to start from, for training one task on top of another",
)
parser.add_argument(
    "--device-override",
    default=None,
    help="force cuda:0 or cpu, for the CPU-versus-GPU wall-clock comparison",
)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Build the environment and agent, then run PPO to `max_iterations`."""
    # Imported after the app starts. These reach into Omniverse extensions that do not
    # exist until Kit is running, and importing `furuta.tasks` is what registers the id.
    import gymnasium as gym
    import torch
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from rsl_rl.runners import OnPolicyRunner

    import furuta.tasks  # noqa: F401  (registration side effect)

    spec = gym.spec(args.task)
    env_cfg = spec.kwargs["env_cfg_entry_point"]()
    agent_cfg = spec.kwargs["rsl_rl_cfg_entry_point"]()

    env_cfg.scene.num_envs = args.num_envs
    if args.velocity_window is not None:
        env_cfg.velocity_window = args.velocity_window
    if args.accel_bound is not None:
        from furuta.parameters import FurutaParameters

        configured = FurutaParameters.from_yaml().max_acceleration_rad_s2
        env_cfg.max_acceleration_rad_s2 = args.accel_bound
        if getattr(env_cfg, "reset_in_recoverable_set", False):
            # The recoverable set grows with the bound, so the resets that are meant to
            # span it grow with it too.
            scale = args.accel_bound / configured
            env_cfg.reset_mode_range = [v * scale for v in env_cfg.reset_mode_range]
        print(
            f"[cfg  ] max_acceleration_rad_s2={args.accel_bound} "
            f"reset_mode_range={getattr(env_cfg, 'reset_mode_range', None)}"
        )

    agent_cfg.seed = args.seed
    if args.max_iterations is not None:
        agent_cfg.max_iterations = args.max_iterations
    if args.device_override is not None:
        env_cfg.sim.device = args.device_override
        agent_cfg.device = args.device_override

    # Runbook defect 4: installing the RL extras can silently replace the CUDA torch
    # with a CPU build, and nothing errors. Every throughput and wall-clock number in
    # the write-up depends on which one is loaded, so it gets printed rather than
    # assumed.
    print(
        f"[stack] torch {torch.__version__} cuda_available={torch.cuda.is_available()}"
    )
    print(
        f"[cfg  ] device={agent_cfg.device} num_envs={args.num_envs} seed={args.seed}"
    )
    print(
        f"[cfg  ] velocity_window={env_cfg.velocity_window}"
        f" gamma={agent_cfg.algorithm.gamma}"
    )

    if args.action_rate_weight is not None:
        env_cfg.rew_scale_action_rate = args.action_rate_weight
        print(f"[cfg  ] rew_scale_action_rate={args.action_rate_weight}")
    if args.rotor_rate_weight is not None:
        env_cfg.rew_scale_rotor_rate = args.rotor_rate_weight
        print(f"[cfg  ] rew_scale_rotor_rate={args.rotor_rate_weight}")
    if args.travel_weight is not None:
        env_cfg.rew_scale_rotor_travel = args.travel_weight
        print(f"[cfg  ] rew_scale_rotor_travel={args.travel_weight}")
    if args.rotor_travel_deadband is not None:
        env_cfg.rotor_travel_deadband_rad = args.rotor_travel_deadband
        print(f"[cfg  ] rotor_travel_deadband_rad={args.rotor_travel_deadband}")

    if args.max_rotor_rad is not None:
        env_cfg.max_rotor_angle_rad = args.max_rotor_rad
        print(f"[cfg  ] max_rotor_angle_rad={args.max_rotor_rad}")

    if args.governor_weight is not None:
        env_cfg.rew_scale_travel_governor = args.governor_weight
        print(f"[cfg  ] rew_scale_travel_governor={args.governor_weight}")

    if args.governor_margin is not None:
        env_cfg.travel_governor_margin_rad = args.governor_margin
        print(f"[cfg  ] travel_governor_margin_rad={args.governor_margin}")

    if args.physics_hz is not None:
        env_cfg.sim.dt = 1.0 / args.physics_hz
        env_cfg.decimation = max(1, round(0.002 * args.physics_hz))
        print(f"[cfg  ] sim.dt={env_cfg.sim.dt} decimation={env_cfg.decimation}")

    if args.velocity_iters is not None:
        env_cfg.sim.physx.min_velocity_iteration_count = args.velocity_iters
        env_cfg.sim.physx.enable_external_forces_every_iteration = True
        print(f"[cfg  ] min_velocity_iteration_count={args.velocity_iters}")

    if args.swing_rate is not None:
        env_cfg.rew_scale_swing_rate = args.swing_rate
        print(f"[cfg  ] rew_scale_swing_rate={args.swing_rate}")

    if args.pump_power is not None:
        env_cfg.rew_scale_pump_power = args.pump_power
        print(f"[cfg  ] rew_scale_pump_power={args.pump_power}")

    if args.rotor_rate_range is not None:
        spread = args.rotor_rate_range
        env_cfg.initial_rotor_rate_range = [-spread, spread]
        print(f"[cfg  ] initial_rotor_rate_range=+/-{args.rotor_rate_range}")

    if args.entropy_coef is not None:
        agent_cfg.algorithm.entropy_coef = args.entropy_coef
        print(f"[cfg  ] entropy_coef={args.entropy_coef}")
    if args.upright_reward is not None:
        env_cfg.upright_reward = args.upright_reward
        print(f"[cfg  ] upright_reward={args.upright_reward}")
    if args.init_noise_std is not None:
        agent_cfg.policy.init_noise_std = args.init_noise_std
        print(f"[cfg  ] init_noise_std={args.init_noise_std}")

    env = gym.make(args.task, cfg=env_cfg, render_mode=None)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    run = args.run_name or f"seed{args.seed}"
    log_dir = Path("logs") / "rsl_rl" / agent_cfg.experiment_name / run
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"[log  ] {log_dir}")

    runner = OnPolicyRunner(
        env, agent_cfg.to_dict(), log_dir=str(log_dir), device=agent_cfg.device
    )
    if args.init_from:
        # Start from another task's weights. The observation and action spaces and the
        # network shape are identical across this project's tasks, so a balance
        # checkpoint loads into a swing-up runner unchanged. `load` also restores the
        # optimizer and the current iteration count; the iteration is reset so the run
        # is logged from zero and `max_iterations` means what it says.
        runner.load(args.init_from)
        runner.current_learning_iteration = 0
        print(f"[init ] weights from {args.init_from}", flush=True)

    runner.learn(
        num_learning_iterations=agent_cfg.max_iterations, init_at_random_ep_len=False
    )

    print(f"[done ] {agent_cfg.max_iterations} iterations, checkpoints in {log_dir}")
    env.close()
    return 0


if __name__ == "__main__":
    main()
    close_and_exit(simulation_app)

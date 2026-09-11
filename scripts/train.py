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
    "--energy-excess-gain",
    type=float,
    default=None,
    help="how much more steeply the energy term charges energy above the separatrix; "
    "1 is the symmetric term. A policy trained from scratch rotated over the "
    "top at 1.24 times the separatrix energy and the symmetric term still paid it 1.5 "
    "of 2.0; at 4 that rotation earns 0.08 and the approach from below is unchanged",
)
parser.add_argument(
    "--action-rate-gate",
    type=float,
    default=None,
    help="tilt from upright, rad, inside which the action-rate charge applies; the "
    "default charges everywhere. 0.35 confines it to the capture window, where the "
    "hold's chatter lives, and stops it taxing the pump's reversals and the "
    "exploration noise a swing-up has to keep",
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
parser.add_argument(
    "--pendulum-rate-weight",
    type=float,
    default=None,
    help="reward weight on the pendulum's speed inside the capture window, per "
    "(rad/s)^2 per step. Negative. Sized against the acceleration bound, because the "
    "recoverable set scales with it: at the configured 11.78 the default -0.25 charges "
    "0.26 for a marginal catchable arrival against a capture term paying 2.0, and at "
    "60 the same weight charges 6.63 for an arrival that is still catchable, so the "
    "policy is paid to stay away from vertical. Scale by (11.78 / bound)^2 to hold the "
    "ratio",
)
parser.add_argument("--run-name", default=None)
parser.add_argument(
    "--init-from",
    default=None,
    help="checkpoint to start from, for training one task on top of another. Loads "
    "the actor, the critic, the exploration std and the optimizer state",
)
parser.add_argument(
    "--init-from-actor",
    default=None,
    help="checkpoint whose actor weights start this run, and nothing else: the "
    "critic, the exploration std and the optimizer start fresh. For building a task "
    "on a policy trained under a different reward, where the critic's values and the "
    "learned std belong to the old task",
)
parser.add_argument(
    "--gamma",
    type=float,
    default=None,
    help="override PPO's discount; 1/(1-gamma) control steps is the horizon",
)
parser.add_argument(
    "--no-value-clip",
    action="store_true",
    help="turn off PPO's clipped value loss. The clip is 0.2 in absolute return units "
    "and the loss takes the larger of the clipped and unclipped errors, so once the "
    "critic's error exceeds 0.2 the clipped branch wins and its gradient is zero: the "
    "critic can close at most 0.2 per update. Returns here run in the thousands",
)
parser.add_argument(
    "--episode-jitter",
    type=float,
    default=None,
    help="fraction of the episode length each episode's time-out is shortened by, "
    "drawn per environment at every reset to keep the environments' clocks mixed. "
    "0.2 on a 10 s episode gives 8 to 10 s episodes",
)
parser.add_argument(
    "--episode-length-s",
    type=float,
    default=None,
    help="override the training episode length in seconds",
)
parser.add_argument(
    "--hanging-fraction",
    type=float,
    default=None,
    help="share of resets that start hanging, the state the evaluation scores",
)
parser.add_argument(
    "--balance-fraction",
    type=float,
    default=None,
    help="share of resets that start near vertical, where the pendulum can be held",
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
    env_cfg.rotor_target_interpolation = not args.stepped_rotor
    agent_cfg = spec.kwargs["rsl_rl_cfg_entry_point"]()

    env_cfg.scene.num_envs = args.num_envs
    if args.velocity_window is not None:
        env_cfg.velocity_window = args.velocity_window
    if args.accel_bound is not None:
        from furuta.parameters import FurutaParameters

        configured = FurutaParameters.from_yaml().max_acceleration_rad_s2
        env_cfg.max_acceleration_rad_s2 = args.accel_bound
        # The recoverable set grows with the bound, so the resets that are meant to
        # span it grow with it too.
        scale = args.accel_bound / configured
        if getattr(env_cfg, "reset_in_recoverable_set", False):
            env_cfg.reset_mode_range = [v * scale for v in env_cfg.reset_mode_range]
        if getattr(env_cfg, "balance_reset_in_recoverable_set", False):
            env_cfg.balance_reset_mode_range = [
                v * scale for v in env_cfg.balance_reset_mode_range
            ]
        print(
            f"[cfg  ] max_acceleration_rad_s2={args.accel_bound} "
            f"reset_mode_range={getattr(env_cfg, 'reset_mode_range', None)} "
            "balance_reset_mode_range="
            f"{getattr(env_cfg, 'balance_reset_mode_range', None)}"
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
    if args.action_rate_gate is not None:
        env_cfg.action_rate_gate_rad = args.action_rate_gate
        print(f"[cfg  ] action_rate_gate_rad={args.action_rate_gate}")
    if args.energy_excess_gain is not None:
        env_cfg.energy_excess_gain = args.energy_excess_gain
        print(f"[cfg  ] energy_excess_gain={args.energy_excess_gain}")
    if args.rotor_rate_weight is not None:
        env_cfg.rew_scale_rotor_rate = args.rotor_rate_weight
        print(f"[cfg  ] rew_scale_rotor_rate={args.rotor_rate_weight}")
    if args.travel_weight is not None:
        env_cfg.rew_scale_rotor_travel = args.travel_weight
        print(f"[cfg  ] rew_scale_rotor_travel={args.travel_weight}")
    if args.pendulum_rate_weight is not None:
        env_cfg.rew_scale_pendulum_rate = args.pendulum_rate_weight
        print(f"[cfg  ] rew_scale_pendulum_rate={args.pendulum_rate_weight}")
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
    if args.gamma is not None:
        agent_cfg.algorithm.gamma = args.gamma
        print(f"[cfg  ] gamma={args.gamma}")
    if args.no_value_clip:
        agent_cfg.algorithm.use_clipped_value_loss = False
        print("[cfg  ] use_clipped_value_loss=False")
    if args.episode_length_s is not None:
        env_cfg.episode_length_s = args.episode_length_s
        print(f"[cfg  ] episode_length_s={args.episode_length_s}")
    if args.episode_jitter is not None:
        env_cfg.episode_length_jitter = args.episode_jitter
        print(f"[cfg  ] episode_length_jitter={args.episode_jitter}")
    if args.hanging_fraction is not None:
        env_cfg.hanging_reset_fraction = args.hanging_fraction
        print(f"[cfg  ] hanging_reset_fraction={args.hanging_fraction}")
    if args.balance_fraction is not None:
        env_cfg.balance_reset_fraction = args.balance_fraction
        print(f"[cfg  ] balance_reset_fraction={args.balance_fraction}")
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
    if args.init_from and args.init_from_actor:
        raise SystemExit("--init-from and --init-from-actor are alternatives")
    if args.init_from:
        # Start from another task's weights. The observation and action spaces and the
        # network shape are identical across this project's tasks, so a balance
        # checkpoint loads into a swing-up runner unchanged. `load` also restores the
        # optimizer and the current iteration count; the iteration is reset so the run
        # is logged from zero and `max_iterations` means what it says.
        runner.load(args.init_from)
        runner.current_learning_iteration = 0
        print(f"[init ] weights from {args.init_from}", flush=True)
    if args.init_from_actor:
        # The actor alone. A balance checkpoint's critic predicts balance returns under
        # balance's discount, its learned std is the quiet 0.25 of a settled hold, and
        # its Adam moments belong to that run; carried into a swing-up they would drive
        # the first updates before the new critic has fitted anything. The critic and
        # std start where a fresh run's would.
        state = torch.load(args.init_from_actor, map_location=agent_cfg.device)
        actor_only = {
            k: v for k, v in state["model_state_dict"].items() if k.startswith("actor.")
        }
        if not actor_only:
            raise SystemExit(f"no actor tensors in {args.init_from_actor}")
        # The base module's loader, called directly: rsl_rl's policy overrides
        # `load_state_dict` to return a bool that says whether a training run resumed,
        # and swallows the missing and unexpected keys this needs to report.
        keys = torch.nn.Module.load_state_dict(
            runner.alg.policy, actor_only, strict=False
        )
        if keys.unexpected_keys:
            raise SystemExit(f"unexpected keys in {args.init_from_actor}: {keys}")
        print(
            f"[init ] actor from {args.init_from_actor}: {len(actor_only)} tensors, "
            f"left fresh: {sorted(keys.missing_keys)}",
            flush=True,
        )

    # Every environment otherwise starts its episode on the same step, and a task that
    # rarely terminates keeps them there. Each 128-step rollout is then the same
    # quarter second of every episode at once, and the from-rest opening the gate
    # scores appears in about a tenth of the iterations and in none of the rest.
    # rsl_rl's `init_at_random_ep_len` does this through the wrapper's setter; the
    # buffer is also written here directly so its spread can be printed as the
    # evidence. A random start does not stop terminations pulling clocks back into
    # step: Experiment 06's run 1 showed a 39-iteration period, one 10 s episode every
    # 39 rollouts of 128 steps, and `--episode-jitter` is the fix.
    inner = env.unwrapped
    inner.episode_length_buf = torch.randint_like(
        inner.episode_length_buf, high=int(inner.max_episode_length)
    )
    spread = inner.episode_length_buf
    print(
        f"[cfg  ] episode clock randomised: min {int(spread.min())} "
        f"max {int(spread.max())} of {int(inner.max_episode_length)} steps",
        flush=True,
    )
    runner.learn(
        num_learning_iterations=agent_cfg.max_iterations, init_at_random_ep_len=True
    )

    print(f"[done ] {agent_cfg.max_iterations} iterations, checkpoints in {log_dir}")
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

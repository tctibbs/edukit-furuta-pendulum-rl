"""Record a video of a policy holding, or failing to hold, the pendulum.

Two clips make the before-and-after pair for an experiment: an untrained policy, whose
weights are freshly initialized, and a trained checkpoint on its mean action. Pass
`--checkpoint` for the second, omit it for the first. `--swingup-camera` reframes for
the swing-up task, whose pendulum spends half its time below the arm.

The camera and the alternate-black-frame defect are the same as
`scripts/record_environment.py`; that script's comments carry the detail.

Run on the training host:

    python -u scripts/record_policy.py --headless --output videos/untrained
    python -u scripts/record_policy.py --headless --output videos/trained
        (adding --checkpoint logs/rsl_rl/furuta_balance/seed1/model_299.pt)
"""

from __future__ import annotations

import argparse

from isaaclab.app import AppLauncher

from furuta.shutdown import close_and_exit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--task", default="Furuta-Balance-Direct-v0")
parser.add_argument("--checkpoint", default=None, help="omit for an untrained policy")
parser.add_argument("--num-envs", type=int, default=9)
parser.add_argument("--steps", type=int, default=1500, help="control steps, 2 ms each")
parser.add_argument("--output", default="videos")
parser.add_argument(
    "--swingup-camera",
    action="store_true",
    help="pull the camera back and drop it, so a hanging pendulum stays in frame",
)
parser.add_argument(
    "--start",
    choices=["config", "hanging", "vertical"],
    default="config",
    help="override the reset spread: hanging near rest, or on top of the arm",
)
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
    "--physics-hz",
    type=float,
    default=None,
    help="override the physics rate; the control rate stays at 500 Hz",
)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

# Offscreen rendering needs the camera extensions, and this script only records.
args.enable_cameras = True
app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Roll the policy out under the recorder and write one clip."""
    import gymnasium as gym
    import torch
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from rsl_rl.runners import OnPolicyRunner

    import furuta.tasks  # noqa: F401  (registration side effect)

    spec = gym.spec(args.task)
    cfg = spec.kwargs["env_cfg_entry_point"]()
    agent_cfg = spec.kwargs["rsl_rl_cfg_entry_point"]()

    cfg.scene.num_envs = args.num_envs
    cfg.scene.env_spacing = 0.85
    cfg.sim.render_interval = 1
    # Framed on one pendulum. The tip reaches the arm height plus the rod, about 0.62 m,
    # so a camera aimed low cuts off the part that shows whether it is balancing, and a
    # camera far enough back for several environments makes each too small to read.
    cfg.viewer.eye = (0.52, -0.62, 0.62)
    cfg.viewer.lookat = (0.06, 0.0, 0.44)
    if args.swingup_camera:
        # Balance keeps the pendulum in a 20 degree cone above the arm. Swing-up sweeps
        # the whole circle, so the tip reaches 0.27 m below the arm as well as above it,
        # and the balance framing cuts off the bottom half of every swing.
        cfg.viewer.eye = (0.62, -0.78, 0.50)
        cfg.viewer.lookat = (0.06, 0.0, 0.34)
    # Long enough that the clip is never cut by the episode timeout. A falling pendulum
    # still resets on the fall-over termination, which is the behaviour being shown.
    cfg.episode_length_s = 1000.0

    if args.max_rotor_rad is not None:
        cfg.max_rotor_angle_rad = args.max_rotor_rad
    if args.no_squash:
        cfg.squash_actions = False
    if args.physics_hz is not None:
        cfg.sim.dt = 1.0 / args.physics_hz
        cfg.decimation = max(1, round(0.002 * args.physics_hz))
        # Keep the render cadence the conversion pipeline was built against. The
        # alternate-black-frame pattern was measured at 1 kHz physics; at other rates
        # probe the first recording's frames before trusting any conversion of it.
        cfg.sim.render_interval = 1
    # The registered tasks reset for training, with mixtures that hand some episodes a
    # pendulum already up. A clip is a single storyline, so the override pins every
    # environment to one start.
    if args.start == "hanging":
        cfg.reset_upright = False
        cfg.hanging_reset_fraction = 0.0
        cfg.balance_reset_fraction = 0.0
        cfg.initial_pendulum_angle_range = [-0.4, 0.4]
        cfg.initial_pendulum_rate_range = [-1.0, 1.0]
    elif args.start == "vertical":
        cfg.hanging_reset_fraction = 0.0
        cfg.balance_reset_fraction = 1.0

    env = gym.make(args.task, cfg=cfg, render_mode="rgb_array")
    env = gym.wrappers.RecordVideo(
        env,
        video_folder=args.output,
        step_trigger=lambda step: step == 0,
        video_length=args.steps,
        disable_logger=True,
    )
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)

    runner = OnPolicyRunner(
        env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device
    )
    if args.checkpoint:
        runner.load(args.checkpoint)
        print(f"[ckpt ] {args.checkpoint}", flush=True)
    else:
        print("[ckpt ] none, recording the untrained policy", flush=True)
    policy = runner.get_inference_policy(device=agent_cfg.device)

    obs = env.get_observations()
    for _ in range(args.steps):
        with torch.inference_mode():
            actions = policy(obs)
        obs, _, _, _ = env.step(actions)

    env.close()
    print(f"[done ] wrote video to {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    main()
    close_and_exit(simulation_app)

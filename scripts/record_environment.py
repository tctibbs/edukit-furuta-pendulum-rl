"""Record video of the pendulum environment under a cosine rotor command.

The command is an acceleration. A sine integrates to a velocity `(A/w)(1 - cos wt)`
that never goes negative, and the rotor creeps one way into its travel bound. A cosine
integrates to `(A/w) sin wt`, and the rotor sweeps back and forth.

The period defaults to 420 control steps, the pendulum's own 0.841 s period. Each
cycle pumps the swing higher and the reaction torque carries the arm further. Over
2500 steps, amplitude 0.8 reached the pi bound at 3.8 s and reset four times.
Amplitude 0.7 peaked at 2.83 rad. A longer clip needs a lower amplitude.

Run on the training host:

    python -u scripts/record_environment.py --headless --steps 600
"""

from __future__ import annotations

import argparse
import math

from isaaclab.app import AppLauncher

# `--steps` and `--period-steps` count 2 ms control steps.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--num-envs", type=int, default=9)
parser.add_argument("--steps", type=int, default=600)
parser.add_argument("--period-steps", type=float, default=420.0)
parser.add_argument("--amplitude", type=float, default=0.7)
parser.add_argument("--output", type=str, default="videos")
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

# Offscreen rendering needs the camera extensions. Same as `--enable_cameras`.
args.enable_cameras = True
app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

TASK = "Furuta-Balance-Direct-v0"


def main() -> int:
    """Step the environment under a cosine rotor command, recording video."""
    # These imports need the app above to be running. Importing `furuta.tasks` also
    # registers TASK with gymnasium.
    import gymnasium as gym
    import torch

    from furuta.tasks import FurutaEnvCfg

    cfg = FurutaEnvCfg()
    # The scene defaults are sized for training, 4096 environments at 1.5 m spacing.
    cfg.scene.num_envs = args.num_envs
    cfg.scene.env_spacing = 1.2
    # Render every step, against a default that renders every `decimation` steps (defect
    # 6 in the training-host runbook). Measured on 2026-08-23 it does not have that
    # effect. A 2500-step capture came back with 1250 black frames, the even-numbered
    # ones. Alternate frames still have to be dropped afterwards.
    cfg.sim.render_interval = 1
    cfg.viewer.eye = (0.55, -0.75, 0.42)
    cfg.viewer.lookat = (0.05, 0.0, 0.22)
    # The 10 s episode timeout would restart a longer clip mid-recording. Move it out
    # of reach. The rotor travel bound is then the only reset.
    cfg.episode_length_s = 1000.0

    env = gym.make(TASK, cfg=cfg, render_mode="rgb_array")
    env = gym.wrappers.RecordVideo(
        env,
        video_folder=args.output,
        step_trigger=lambda step: step == 0,
        video_length=args.steps,
        disable_logger=True,
    )
    env.reset()

    device = env.unwrapped.device
    # A normalized rotor acceleration, clipped to [-1, 1] and scaled by
    # `max_acceleration_rad_s2`. Every environment gets the same command. They differ
    # only in their starting pendulum angle.
    for step in range(args.steps):
        phase = 2.0 * math.pi * step / args.period_steps
        command = args.amplitude * math.cos(phase)
        action = torch.full((args.num_envs, 1), command, device=device)
        env.step(action)

    env.close()
    print(f"[done] wrote video to {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    code = main()
    # Closing the app ends the process and drops buffered stdout. The print above
    # flushes. The documented command runs `python -u`.
    simulation_app.close()
    raise SystemExit(code)

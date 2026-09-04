"""Step the pendulum environment headless and report throughput and tracking error.

One `env.step` advances every environment together, so throughput is the environment
count divided by the time one step takes. Tracking error is the distance between the
rotor joint and the actuator's position target, in microsteps.

Run one environment count per invocation, on the training host:

    python scripts/bench_environment.py --headless --num-envs 512
"""

from __future__ import annotations

import argparse
import time

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--num-envs", type=int, default=512)
parser.add_argument("--steps", type=int, default=200)
# Adds `--headless` and the other app flags.
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

TASK = "Furuta-Balance-Direct-v0"


def main() -> int:
    """Step one configuration and print its timings and tracking error."""
    # These imports need the app above to be running. Importing `furuta.tasks` also
    # registers TASK with gymnasium.
    import gymnasium as gym
    import torch

    from furuta.env import PARAMS
    from furuta.tasks import FurutaEnvCfg

    cfg = FurutaEnvCfg()
    cfg.scene.num_envs = args.num_envs
    env = gym.make(TASK, cfg=cfg, render_mode=None)
    env.reset()

    unwrapped = env.unwrapped
    # A constant, non-zero acceleration. 0.25 of full scale is 2.95 rad/s^2.
    action = torch.full((args.num_envs, 1), 0.25, device=unwrapped.device)

    # Warm up to keep kernel compilation out of the measurement.
    for _ in range(20):
        env.step(action)

    # CUDA work is still queued when a step returns. Synchronizing before and after the
    # timed loop makes `perf_counter` time the work itself.
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    start = time.perf_counter()
    for _ in range(args.steps):
        env.step(action)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    rotor_idx = unwrapped._rotor_idx[0]
    actual = unwrapped.robot.data.joint_pos[:, rotor_idx]
    # Largest gap between the rotor joint and its target across environments, after the
    # last step only. One microstep is the stepper's smallest motion.
    error = torch.abs(actual - unwrapped._rotor_target).max().item()

    steps_per_s = args.num_envs * args.steps / elapsed
    print()
    print("=" * 62)
    print(f"envs                  {args.num_envs}")
    print(f"throughput            {steps_per_s:,.0f} steps/s")
    print(f"step time             {1000.0 * elapsed / args.steps:.2f} ms")
    print(f"rotor tracking error  {error:.3e} rad")
    print(f"                      {error / PARAMS.rad_per_microstep:.2f} microsteps")
    print("=" * 62)
    print("  above one microstep means the rotor is not holding position")
    return 0


if __name__ == "__main__":
    code = main()
    simulation_app.close()
    raise SystemExit(code)
